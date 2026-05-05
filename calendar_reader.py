"""
Outlook calendar reader using Microsoft Graph API.

Setup:
1. Copy .env.example to .env and fill in your Azure AD credentials.
2. Register an app at https://portal.azure.com -> Azure AD -> App registrations.
   - Add redirect URI: http://localhost (type: Public client/native)
   - Grant delegated permissions: Calendars.Read, Mail.Read
3. pip install -r requirements.txt
4. python calendar_reader.py --next        # next meeting today
   python calendar_reader.py --today       # all meetings today
   python calendar_reader.py --week        # meetings this week
"""

import os
import sys
import json
from datetime import datetime, timezone, timedelta

import msal
import requests
from dotenv import load_dotenv

load_dotenv()

GRAPH_BASE = "https://graph.microsoft.com/v1.0"
SCOPES = ["Calendars.Read", "Mail.Read"]

CLIENT_ID = os.environ.get("AZURE_CLIENT_ID")
TENANT_ID = os.environ.get("AZURE_TENANT_ID", "common")


def _build_app() -> msal.PublicClientApplication:
    authority = f"https://login.microsoftonline.com/{TENANT_ID}"
    return msal.PublicClientApplication(CLIENT_ID, authority=authority)


def _acquire_token(app: msal.PublicClientApplication) -> str:
    accounts = app.get_accounts()
    if accounts:
        result = app.acquire_token_silent(SCOPES, account=accounts[0])
        if result and "access_token" in result:
            return result["access_token"]

    flow = app.initiate_device_flow(scopes=SCOPES)
    if "user_code" not in flow:
        raise RuntimeError(f"Failed to create device flow: {flow.get('error_description')}")

    print(flow["message"], file=sys.stderr)
    result = app.acquire_token_by_device_flow(flow)

    if "access_token" not in result:
        raise RuntimeError(
            f"Authentication failed: {result.get('error_description', result.get('error'))}"
        )
    return result["access_token"]


def _get(token: str, path: str, params: dict = None) -> dict:
    resp = requests.get(
        f"{GRAPH_BASE}{path}",
        headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
        params=params,
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def _parse_event_dt(event: dict, key: str) -> datetime | None:
    dt_obj = event.get(key, {})
    dt_str = dt_obj.get("dateTime")
    tz_str = dt_obj.get("timeZone", "UTC")
    if not dt_str:
        return None
    try:
        dt = datetime.fromisoformat(dt_str.rstrip("Z"))
        if dt.tzinfo is None:
            # Graph returns naive datetimes in the event's local timezone
            # Treat as UTC for comparison; real deployments should use pytz/zoneinfo
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


def _format_event(event: dict) -> dict:
    start = _parse_event_dt(event, "start")
    end = _parse_event_dt(event, "end")
    attendees = [
        a.get("emailAddress", {}).get("name") or a.get("emailAddress", {}).get("address", "")
        for a in event.get("attendees", [])
    ]
    return {
        "subject": event.get("subject", "(no subject)"),
        "start": start.strftime("%H:%M") if start else "?",
        "end": end.strftime("%H:%M") if end else "?",
        "start_iso": start.isoformat() if start else None,
        "organizer": event.get("organizer", {}).get("emailAddress", {}).get("name", ""),
        "location": event.get("location", {}).get("displayName", ""),
        "is_online": event.get("isOnlineMeeting", False),
        "status": event.get("showAs", ""),
        "attendees": attendees[:8],
        "body_preview": event.get("bodyPreview", "")[:120],
    }


def get_events(token: str, start_dt: datetime, end_dt: datetime) -> list[dict]:
    params = {
        "startDateTime": start_dt.strftime("%Y-%m-%dT%H:%M:%S"),
        "endDateTime": end_dt.strftime("%Y-%m-%dT%H:%M:%S"),
        "$orderby": "start/dateTime",
        "$select": "subject,start,end,organizer,attendees,location,isOnlineMeeting,showAs,bodyPreview",
        "$top": 50,
    }
    data = _get(token, "/me/calendarView", params=params)
    return [_format_event(e) for e in data.get("value", [])]


def get_today_events(token: str) -> list[dict]:
    now = datetime.now(timezone.utc)
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=1)
    return get_events(token, start, end)


def get_week_events(token: str) -> list[dict]:
    now = datetime.now(timezone.utc)
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=7)
    return get_events(token, start, end)


def get_next_meeting(token: str) -> dict | None:
    now = datetime.now(timezone.utc)
    end = now.replace(hour=23, minute=59, second=59)
    events = get_events(token, now, end)
    return events[0] if events else None


def print_events(events: list[dict]) -> None:
    if not events:
        print("No meetings found.")
        return
    for e in events:
        online = " [Teams]" if e["is_online"] else ""
        loc = f" — {e['location']}" if e["location"] and not e["is_online"] else ""
        print(f"  {e['start']}–{e['end']}  {e['subject']}{online}{loc}")
        if e["organizer"]:
            print(f"             Organizer: {e['organizer']}")


def main() -> None:
    if not CLIENT_ID:
        sys.exit(
            "Error: AZURE_CLIENT_ID not set. Copy .env.example to .env and fill in your credentials."
        )

    app = _build_app()
    token = _acquire_token(app)

    flag = sys.argv[1] if len(sys.argv) > 1 else "--next"

    if flag == "--next":
        meeting = get_next_meeting(token)
        if meeting:
            print(json.dumps(meeting, indent=2))
        else:
            print(json.dumps({"message": "No more meetings today."}))

    elif flag == "--today":
        events = get_today_events(token)
        if "--json" in sys.argv:
            print(json.dumps(events, indent=2))
        else:
            print(f"\nToday's meetings ({len(events)}):")
            print_events(events)

    elif flag == "--week":
        events = get_week_events(token)
        if "--json" in sys.argv:
            print(json.dumps(events, indent=2))
        else:
            print(f"\nThis week's meetings ({len(events)}):")
            print_events(events)

    else:
        print(f"Unknown flag: {flag}")
        print("Usage: python calendar_reader.py [--next | --today | --week] [--json]")
        sys.exit(1)


if __name__ == "__main__":
    main()
