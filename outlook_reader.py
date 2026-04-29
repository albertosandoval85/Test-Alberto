"""
Outlook email reader using Microsoft Graph API.

Setup:
1. Copy .env.example to .env and fill in your Azure AD credentials.
2. Register an app at https://portal.azure.com -> Azure AD -> App registrations.
   - Add redirect URI: http://localhost (type: Public client/native)
   - Grant delegated permission: Mail.Read
3. pip install -r requirements.txt
4. python outlook_reader.py
"""

import os
import sys
import json
from datetime import datetime

import msal
import requests
from dotenv import load_dotenv

load_dotenv()

GRAPH_BASE = "https://graph.microsoft.com/v1.0"
SCOPES = ["Mail.Read"]

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

    # Interactive device-code flow (works in terminals without a browser on the same machine)
    flow = app.initiate_device_flow(scopes=SCOPES)
    if "user_code" not in flow:
        raise RuntimeError(f"Failed to create device flow: {flow.get('error_description')}")

    print(flow["message"])  # prints the URL + code the user must visit
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


def _format_date(iso: str) -> str:
    try:
        dt = datetime.fromisoformat(iso.rstrip("Z"))
        return dt.strftime("%Y-%m-%d %H:%M")
    except Exception:
        return iso


def list_emails(token: str, folder: str = "inbox", top: int = 10) -> list[dict]:
    data = _get(
        token,
        f"/me/mailFolders/{folder}/messages",
        params={
            "$top": top,
            "$orderby": "receivedDateTime desc",
            "$select": "id,subject,from,receivedDateTime,isRead,bodyPreview",
        },
    )
    return data.get("value", [])


def get_email(token: str, message_id: str) -> dict:
    return _get(token, f"/me/messages/{message_id}")


def print_email_list(emails: list[dict]) -> None:
    if not emails:
        print("No emails found.")
        return
    print(f"\n{'#':<4} {'Date':<17} {'Read':<5} {'From':<30} Subject")
    print("-" * 90)
    for i, msg in enumerate(emails, 1):
        sender = msg.get("from", {}).get("emailAddress", {})
        name = sender.get("name") or sender.get("address", "Unknown")[:28]
        date = _format_date(msg.get("receivedDateTime", ""))
        read = " " if msg.get("isRead") else "*"
        subject = (msg.get("subject") or "(no subject)")[:40]
        print(f"{i:<4} {date:<17} {read:<5} {name:<30} {subject}")


def print_email_detail(msg: dict) -> None:
    sender = msg.get("from", {}).get("emailAddress", {})
    to_list = [r["emailAddress"].get("address", "") for r in msg.get("toRecipients", [])]
    print(f"\nFrom   : {sender.get('name')} <{sender.get('address')}>")
    print(f"To     : {', '.join(to_list)}")
    print(f"Date   : {_format_date(msg.get('receivedDateTime', ''))}")
    print(f"Subject: {msg.get('subject', '(no subject)')}")
    print("-" * 70)
    body = msg.get("body", {})
    if body.get("contentType") == "text":
        print(body.get("content", ""))
    else:
        # Strip basic HTML tags for terminal display
        import re
        text = re.sub(r"<[^>]+>", "", body.get("content", ""))
        text = re.sub(r"\n{3,}", "\n\n", text).strip()
        print(text)


def interactive_menu(token: str) -> None:
    folder = "inbox"
    top = 10
    emails = []

    while True:
        print(f"\n=== Outlook Reader  [folder: {folder}] ===")
        print("1. List emails")
        print("2. Read email (by number)")
        print("3. Change folder")
        print("4. Change email count")
        print("q. Quit")
        choice = input("Choice: ").strip().lower()

        if choice == "q":
            break
        elif choice == "1":
            emails = list_emails(token, folder=folder, top=top)
            print_email_list(emails)
        elif choice == "2":
            if not emails:
                print("List emails first (option 1).")
                continue
            try:
                num = int(input(f"Email number (1-{len(emails)}): "))
                msg = get_email(token, emails[num - 1]["id"])
                print_email_detail(msg)
            except (ValueError, IndexError):
                print("Invalid selection.")
        elif choice == "3":
            folder = input("Folder name (inbox/sentItems/drafts/deletedItems): ").strip() or "inbox"
        elif choice == "4":
            try:
                top = int(input("Number of emails to fetch (1-50): "))
            except ValueError:
                print("Invalid number.")
        else:
            print("Unknown option.")


def main() -> None:
    if not CLIENT_ID:
        sys.exit(
            "Error: AZURE_CLIENT_ID not set. Copy .env.example to .env and fill in your credentials."
        )

    print("Authenticating with Microsoft...")
    app = _build_app()
    token = _acquire_token(app)
    print("Authentication successful.")

    if len(sys.argv) > 1:
        # Non-interactive: dump inbox as JSON
        flag = sys.argv[1]
        if flag == "--json":
            top = int(sys.argv[2]) if len(sys.argv) > 2 else 10
            emails = list_emails(token, top=top)
            print(json.dumps(emails, indent=2))
        else:
            print(f"Unknown flag: {flag}")
            sys.exit(1)
    else:
        interactive_menu(token)


if __name__ == "__main__":
    main()
