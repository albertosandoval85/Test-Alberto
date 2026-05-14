"""
Market data fetcher using yfinance.
Handles stocks, indices, crypto, commodities, forex, pre/post market.
"""
from __future__ import annotations

import time
import threading
from datetime import datetime, timedelta
from typing import Optional

import pandas as pd
import numpy as np
import yfinance as yf

# ─── Cache simple con TTL ──────────────────────────────────────────────────────
_cache: dict[str, tuple[float, object]] = {}
_cache_lock = threading.Lock()

QUOTE_TTL = 30        # segundos para cotizaciones
HISTORY_TTL = 300     # segundos para histórico
INFO_TTL = 3600       # segundos para info de empresa


def _get_cache(key: str, ttl: float) -> Optional[object]:
    with _cache_lock:
        entry = _cache.get(key)
        if entry and (time.time() - entry[0]) < ttl:
            return entry[1]
    return None


def _set_cache(key: str, value: object):
    with _cache_lock:
        _cache[key] = (time.time(), value)


# ─── Cotización en tiempo real ─────────────────────────────────────────────────
def get_quote(symbol: str) -> dict:
    """Retorna cotización actual con pre/post market."""
    cached = _get_cache(f"quote:{symbol}", QUOTE_TTL)
    if cached:
        return cached

    try:
        tk = yf.Ticker(symbol)
        info = tk.fast_info

        price = getattr(info, "last_price", None) or 0.0
        prev_close = getattr(info, "previous_close", None) or price
        open_price = getattr(info, "open", None) or price
        day_high = getattr(info, "day_high", None) or price
        day_low = getattr(info, "day_low", None) or price
        volume = getattr(info, "last_volume", None) or 0
        market_cap = getattr(info, "market_cap", None) or 0

        change = price - prev_close if prev_close else 0.0
        change_pct = (change / prev_close * 100) if prev_close else 0.0

        # Pre/post market
        pre_price = None
        post_price = None
        try:
            full_info = tk.info
            pre_price = full_info.get("preMarketPrice")
            post_price = full_info.get("postMarketPrice")
        except Exception:
            pass

        result = {
            "symbol": symbol,
            "price": price,
            "prev_close": prev_close,
            "open": open_price,
            "high": day_high,
            "low": day_low,
            "volume": volume,
            "market_cap": market_cap,
            "change": change,
            "change_pct": change_pct,
            "pre_market": pre_price,
            "post_market": post_price,
            "timestamp": datetime.now(),
        }
        _set_cache(f"quote:{symbol}", result)
        return result
    except Exception as e:
        return _empty_quote(symbol)


def _empty_quote(symbol: str) -> dict:
    return {
        "symbol": symbol, "price": 0.0, "prev_close": 0.0, "open": 0.0,
        "high": 0.0, "low": 0.0, "volume": 0, "market_cap": 0,
        "change": 0.0, "change_pct": 0.0,
        "pre_market": None, "post_market": None,
        "timestamp": datetime.now(),
    }


def get_quotes_bulk(symbols: list[str]) -> dict[str, dict]:
    """Descarga múltiples cotizaciones de forma eficiente."""
    results = {}
    uncached = []
    for s in symbols:
        cached = _get_cache(f"quote:{s}", QUOTE_TTL)
        if cached:
            results[s] = cached
        else:
            uncached.append(s)

    if not uncached:
        return results

    try:
        tickers = yf.Tickers(" ".join(uncached))
        for s in uncached:
            try:
                tk = tickers.tickers[s]
                info = tk.fast_info
                price = getattr(info, "last_price", None) or 0.0
                prev_close = getattr(info, "previous_close", None) or price
                change = price - prev_close if prev_close else 0.0
                change_pct = (change / prev_close * 100) if prev_close else 0.0
                q = {
                    "symbol": s,
                    "price": price,
                    "prev_close": prev_close,
                    "open": getattr(info, "open", None) or price,
                    "high": getattr(info, "day_high", None) or price,
                    "low": getattr(info, "day_low", None) or price,
                    "volume": getattr(info, "last_volume", None) or 0,
                    "market_cap": getattr(info, "market_cap", None) or 0,
                    "change": change,
                    "change_pct": change_pct,
                    "pre_market": None,
                    "post_market": None,
                    "timestamp": datetime.now(),
                }
                _set_cache(f"quote:{s}", q)
                results[s] = q
            except Exception:
                results[s] = _empty_quote(s)
    except Exception:
        for s in uncached:
            results[s] = _empty_quote(s)

    return results


# ─── Información de empresa ────────────────────────────────────────────────────
def get_company_info(symbol: str) -> dict:
    cached = _get_cache(f"info:{symbol}", INFO_TTL)
    if cached:
        return cached

    try:
        info = yf.Ticker(symbol).info
        result = {
            "name": info.get("longName") or info.get("shortName", symbol),
            "sector": info.get("sector", "N/A"),
            "industry": info.get("industry", "N/A"),
            "country": info.get("country", "N/A"),
            "market_cap": info.get("marketCap", 0),
            "pe_ratio": info.get("trailingPE"),
            "forward_pe": info.get("forwardPE"),
            "pb_ratio": info.get("priceToBook"),
            "eps": info.get("trailingEps"),
            "dividend_yield": info.get("dividendYield"),
            "beta": info.get("beta"),
            "52w_high": info.get("fiftyTwoWeekHigh"),
            "52w_low": info.get("fiftyTwoWeekLow"),
            "avg_volume": info.get("averageVolume"),
            "description": info.get("longBusinessSummary", ""),
            "employees": info.get("fullTimeEmployees"),
            "website": info.get("website", ""),
        }
        _set_cache(f"info:{symbol}", result)
        return result
    except Exception:
        return {"name": symbol, "sector": "N/A", "industry": "N/A", "country": "N/A",
                "market_cap": 0, "pe_ratio": None, "forward_pe": None, "pb_ratio": None,
                "eps": None, "dividend_yield": None, "beta": None,
                "52w_high": None, "52w_low": None, "avg_volume": None,
                "description": "", "employees": None, "website": ""}


# ─── Datos históricos ──────────────────────────────────────────────────────────
def get_history(symbol: str, period: str = "3mo", interval: str = "1d") -> pd.DataFrame:
    """
    Retorna DataFrame con OHLCV histórico.
    period: 1d, 5d, 1mo, 3mo, 6mo, 1y, 2y, 5y
    interval: 1m, 5m, 15m, 30m, 1h, 1d, 1wk, 1mo
    """
    key = f"hist:{symbol}:{period}:{interval}"
    cached = _get_cache(key, HISTORY_TTL)
    if cached is not None:
        return cached

    try:
        df = yf.download(symbol, period=period, interval=interval,
                         progress=False, auto_adjust=True)
        if df.empty:
            return pd.DataFrame()
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        df = df.dropna()
        _set_cache(key, df)
        return df
    except Exception:
        return pd.DataFrame()


# ─── Correlación entre activos ─────────────────────────────────────────────────
def get_correlation_matrix(symbols: list[str], period: str = "3mo") -> pd.DataFrame:
    """Matriz de correlación entre símbolos (como Bloomberg relaciona empresas)."""
    key = f"corr:{':'.join(sorted(symbols))}:{period}"
    cached = _get_cache(key, HISTORY_TTL)
    if cached is not None:
        return cached

    try:
        data = {}
        for s in symbols:
            df = get_history(s, period=period, interval="1d")
            if not df.empty and "Close" in df.columns:
                data[s] = df["Close"]

        if len(data) < 2:
            return pd.DataFrame()

        prices = pd.DataFrame(data).dropna()
        returns = prices.pct_change().dropna()
        corr = returns.corr()
        _set_cache(key, corr)
        return corr
    except Exception:
        return pd.DataFrame()


# ─── Formato de números ────────────────────────────────────────────────────────
def fmt_price(v: float, decimals: int = 2) -> str:
    if v is None:
        return "N/A"
    return f"{v:,.{decimals}f}"


def fmt_change(v: float) -> str:
    if v is None:
        return "N/A"
    sign = "+" if v >= 0 else ""
    return f"{sign}{v:.2f}%"


def fmt_market_cap(v: float) -> str:
    if not v:
        return "N/A"
    if v >= 1e12:
        return f"${v/1e12:.2f}T"
    if v >= 1e9:
        return f"${v/1e9:.2f}B"
    if v >= 1e6:
        return f"${v/1e6:.2f}M"
    return f"${v:,.0f}"


def fmt_volume(v: int) -> str:
    if not v:
        return "N/A"
    if v >= 1e9:
        return f"{v/1e9:.2f}B"
    if v >= 1e6:
        return f"{v/1e6:.2f}M"
    if v >= 1e3:
        return f"{v/1e3:.1f}K"
    return str(v)


def is_market_open(market: str = "US") -> tuple[bool, str]:
    """Verifica si el mercado está abierto. Retorna (open, status_str)."""
    now_utc = datetime.utcnow()
    # NYSE/NASDAQ: 9:30am-4:00pm ET (UTC-4 o UTC-5)
    if market == "US":
        import pytz
        et = pytz.timezone("America/New_York")
        now_et = datetime.now(et)
        weekday = now_et.weekday()
        if weekday >= 5:
            return False, "CERRADO (fin de semana)"
        open_time = now_et.replace(hour=9, minute=30, second=0, microsecond=0)
        close_time = now_et.replace(hour=16, minute=0, second=0, microsecond=0)
        pre_open = now_et.replace(hour=4, minute=0, second=0, microsecond=0)
        post_close = now_et.replace(hour=20, minute=0, second=0, microsecond=0)

        if open_time <= now_et < close_time:
            return True, "ABIERTO"
        elif pre_open <= now_et < open_time:
            return False, "PRE-MARKET"
        elif close_time <= now_et < post_close:
            return False, "POST-MARKET"
        else:
            return False, "CERRADO"

    elif market == "MX":
        import pytz
        mx = pytz.timezone("America/Mexico_City")
        now_mx = datetime.now(mx)
        weekday = now_mx.weekday()
        if weekday >= 5:
            return False, "CERRADO (fin de semana)"
        open_time = now_mx.replace(hour=8, minute=30, second=0, microsecond=0)
        close_time = now_mx.replace(hour=15, minute=0, second=0, microsecond=0)
        if open_time <= now_mx < close_time:
            return True, "ABIERTO"
        return False, "CERRADO"

    return False, "N/A"
