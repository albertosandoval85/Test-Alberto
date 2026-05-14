"""
Banxico SIE API - CETES, tipo de cambio, TIIE, inflación.
Token gratuito: https://www.banxico.org.mx/SieAPIRest/service/v1/token
"""
from __future__ import annotations

import time
import requests
from datetime import datetime, timedelta
from typing import Optional

BASE_URL = "https://www.banxico.org.mx/SieAPIRest/service/v1/series"

_cache: dict[str, tuple[float, object]] = {}
CACHE_TTL = 3600  # 1 hora (datos de Banxico son diarios)


def _get_cache(key: str) -> Optional[object]:
    entry = _cache.get(key)
    if entry and (time.time() - entry[0]) < CACHE_TTL:
        return entry[1]
    return None


def _set_cache(key: str, value: object):
    _cache[key] = (time.time(), value)


def fetch_series(series_id: str, token: str, n_observations: int = 1) -> Optional[dict]:
    """
    Obtiene la última observación de una serie del SIE de Banxico.
    Retorna {"value": float, "date": str} o None si falla.
    """
    if not token:
        return None

    key = f"banxico:{series_id}"
    cached = _get_cache(key)
    if cached:
        return cached

    url = f"{BASE_URL}/{series_id}/datos/oportuno"
    headers = {"Bmx-Token": token, "Accept": "application/json"}

    try:
        resp = requests.get(url, headers=headers, timeout=10)
        if resp.status_code != 200:
            return None

        data = resp.json()
        series_data = data.get("bmx", {}).get("series", [])
        if not series_data:
            return None

        datos = series_data[0].get("datos", [])
        if not datos:
            return None

        latest = datos[-1]
        val_str = latest.get("dato", "N/A")

        try:
            value = float(val_str.replace(",", ""))
        except (ValueError, AttributeError):
            value = None

        result = {
            "series_id": series_id,
            "value": value,
            "date": latest.get("fecha", "N/A"),
            "raw": val_str,
        }
        _set_cache(key, result)
        return result

    except Exception:
        return None


def fetch_series_history(series_id: str, token: str, days: int = 365) -> list[dict]:
    """Obtiene el historial de una serie para graficar."""
    if not token:
        return []

    key = f"banxico_hist:{series_id}:{days}"
    cached = _get_cache(key)
    if cached:
        return cached

    fecha_fin = datetime.now().strftime("%Y-%m-%d")
    fecha_ini = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    url = f"{BASE_URL}/{series_id}/datos/{fecha_ini}/{fecha_fin}"
    headers = {"Bmx-Token": token, "Accept": "application/json"}

    try:
        resp = requests.get(url, headers=headers, timeout=15)
        if resp.status_code != 200:
            return []

        data = resp.json()
        series_data = data.get("bmx", {}).get("series", [])
        if not series_data:
            return []

        datos = series_data[0].get("datos", [])
        result = []
        for d in datos:
            try:
                val = float(d["dato"].replace(",", ""))
                result.append({"date": d["fecha"], "value": val})
            except Exception:
                continue

        _set_cache(key, result)
        return result

    except Exception:
        return []


def get_all_banxico_data(token: str) -> dict:
    """
    Obtiene todos los indicadores clave de Banxico.
    Retorna dict con nombre → valor.
    """
    from bloomberg.config import BANXICO_SERIES

    results = {}
    for series_id, name in BANXICO_SERIES.items():
        data = fetch_series(series_id, token)
        results[name] = {
            "value": data["value"] if data else None,
            "date": data["date"] if data else "N/A",
            "series_id": series_id,
        }
    return results


def get_cetes_summary(token: str) -> list[dict]:
    """Retorna tabla resumida de CETES."""
    cetes_series = {
        "SF43936": ("28 días",  28),
        "SF43939": ("91 días",  91),
        "SF43942": ("182 días", 182),
        "SF43945": ("364 días", 364),
    }
    results = []
    for sid, (label, days) in cetes_series.items():
        data = fetch_series(sid, token)
        val = data["value"] if data else None
        date = data["date"] if data else "N/A"
        # Rendimiento mensual aproximado
        monthly = (val / 12) if val else None
        results.append({
            "plazo": label,
            "days": days,
            "tasa_anual": val,
            "tasa_mensual": monthly,
            "fecha": date,
        })
    return results


def get_tipo_cambio(token: str) -> Optional[float]:
    """Obtiene el tipo de cambio USD/MXN FIX de Banxico."""
    data = fetch_series("SF63528", token)
    if data and data["value"]:
        return data["value"]
    # Fallback: yfinance
    try:
        import yfinance as yf
        tk = yf.Ticker("MXN=X")
        info = tk.fast_info
        return getattr(info, "last_price", None)
    except Exception:
        return None
