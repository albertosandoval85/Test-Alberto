"""
Technical analysis indicators: RSI, MACD, Bollinger Bands, EMA, SMA,
Stochastic, ATR, OBV, VWAP, soporte/resistencia, señales de compra/venta.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional
import numpy as np
import pandas as pd

try:
    import ta
    HAS_TA = True
except ImportError:
    HAS_TA = False


@dataclass
class TechnicalSignal:
    indicator: str
    value: float
    signal: str          # "BUY" | "SELL" | "NEUTRAL"
    strength: float      # 0.0 – 1.0
    description: str


@dataclass
class TechnicalSummary:
    symbol: str
    rsi: Optional[float] = None
    macd: Optional[float] = None
    macd_signal: Optional[float] = None
    macd_hist: Optional[float] = None
    bb_upper: Optional[float] = None
    bb_middle: Optional[float] = None
    bb_lower: Optional[float] = None
    bb_pct: Optional[float] = None          # posición dentro de BB (0–1)
    ema_20: Optional[float] = None
    ema_50: Optional[float] = None
    ema_200: Optional[float] = None
    sma_20: Optional[float] = None
    sma_50: Optional[float] = None
    stoch_k: Optional[float] = None
    stoch_d: Optional[float] = None
    atr: Optional[float] = None
    obv: Optional[float] = None
    adx: Optional[float] = None
    cci: Optional[float] = None
    williams_r: Optional[float] = None
    support: Optional[float] = None
    resistance: Optional[float] = None
    signals: list[TechnicalSignal] = field(default_factory=list)
    overall_signal: str = "NEUTRAL"        # BUY | SELL | NEUTRAL
    buy_score: int = 0
    sell_score: int = 0
    neutral_score: int = 0


# ─── Cálculo manual de indicadores (sin librería ta) ──────────────────────────
def _rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1/period, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1/period, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def _ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()


def _sma(series: pd.Series, period: int) -> pd.Series:
    return series.rolling(window=period).mean()


def _macd(close: pd.Series, fast=12, slow=26, signal=9):
    ema_fast = _ema(close, fast)
    ema_slow = _ema(close, slow)
    macd_line = ema_fast - ema_slow
    signal_line = _ema(macd_line, signal)
    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram


def _bollinger(close: pd.Series, period=20, std_dev=2.0):
    sma = _sma(close, period)
    std = close.rolling(window=period).std()
    upper = sma + std_dev * std
    lower = sma - std_dev * std
    return upper, sma, lower


def _stochastic(high: pd.Series, low: pd.Series, close: pd.Series, k=14, d=3):
    lowest_low = low.rolling(window=k).min()
    highest_high = high.rolling(window=k).max()
    k_pct = 100 * (close - lowest_low) / (highest_high - lowest_low + 1e-10)
    d_pct = k_pct.rolling(window=d).mean()
    return k_pct, d_pct


def _atr(high: pd.Series, low: pd.Series, close: pd.Series, period=14) -> pd.Series:
    tr1 = high - low
    tr2 = (high - close.shift()).abs()
    tr3 = (low - close.shift()).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    return tr.rolling(window=period).mean()


def _obv(close: pd.Series, volume: pd.Series) -> pd.Series:
    direction = np.sign(close.diff()).fillna(0)
    return (direction * volume).cumsum()


def _adx(high, low, close, period=14) -> pd.Series:
    tr = _atr(high, low, close, period).rename("ATR")
    up = high.diff()
    down = -low.diff()
    pos_dm = up.where((up > down) & (up > 0), 0)
    neg_dm = down.where((down > up) & (down > 0), 0)
    pos_di = 100 * _ema(pos_dm, period) / (tr + 1e-10)
    neg_di = 100 * _ema(neg_dm, period) / (tr + 1e-10)
    dx = 100 * (pos_di - neg_di).abs() / (pos_di + neg_di + 1e-10)
    return _ema(dx, period)


def _cci(high, low, close, period=20) -> pd.Series:
    tp = (high + low + close) / 3
    sma_tp = tp.rolling(window=period).mean()
    mad = tp.rolling(window=period).apply(lambda x: np.mean(np.abs(x - np.mean(x))), raw=True)
    return (tp - sma_tp) / (0.015 * mad + 1e-10)


def _support_resistance(close: pd.Series, window: int = 20) -> tuple[float, float]:
    """Detecta niveles de soporte y resistencia por máximos/mínimos locales."""
    if len(close) < window * 2:
        return close.min(), close.max()
    recent = close.tail(window * 3)
    local_min = recent[(recent.shift(1) >= recent) & (recent.shift(-1) >= recent)]
    local_max = recent[(recent.shift(1) <= recent) & (recent.shift(-1) <= recent)]
    support = float(local_min.mean()) if not local_min.empty else float(recent.min())
    resistance = float(local_max.mean()) if not local_max.empty else float(recent.max())
    return support, resistance


# ─── Función principal ─────────────────────────────────────────────────────────
def analyze(df: pd.DataFrame, symbol: str = "") -> TechnicalSummary:
    """
    Calcula todos los indicadores técnicos sobre el DataFrame OHLCV.
    Genera señales de compra/venta con puntaje ponderado.
    """
    summary = TechnicalSummary(symbol=symbol)

    if df.empty or len(df) < 30:
        return summary

    # Asegurar columnas correctas
    close = df["Close"].astype(float).squeeze()
    high = df["High"].astype(float).squeeze() if "High" in df.columns else close
    low = df["Low"].astype(float).squeeze() if "Low" in df.columns else close
    volume = df["Volume"].astype(float).squeeze() if "Volume" in df.columns else pd.Series(dtype=float)

    current_price = float(close.iloc[-1])

    # ── RSI ──────────────────────────────────────────────────────────────────
    rsi_series = _rsi(close)
    rsi_val = float(rsi_series.iloc[-1]) if not rsi_series.empty else None
    summary.rsi = rsi_val
    if rsi_val is not None:
        if rsi_val < 30:
            summary.signals.append(TechnicalSignal("RSI", rsi_val, "BUY", min((30 - rsi_val) / 30, 1.0),
                f"RSI={rsi_val:.1f} — Sobreventa (BUY)"))
        elif rsi_val > 70:
            summary.signals.append(TechnicalSignal("RSI", rsi_val, "SELL", min((rsi_val - 70) / 30, 1.0),
                f"RSI={rsi_val:.1f} — Sobrecompra (SELL)"))
        elif rsi_val > 50:
            summary.signals.append(TechnicalSignal("RSI", rsi_val, "NEUTRAL", 0.3,
                f"RSI={rsi_val:.1f} — Momentum alcista"))
        else:
            summary.signals.append(TechnicalSignal("RSI", rsi_val, "NEUTRAL", 0.3,
                f"RSI={rsi_val:.1f} — Momentum bajista"))

    # ── MACD ─────────────────────────────────────────────────────────────────
    macd_line, macd_sig, macd_hist = _macd(close)
    summary.macd = float(macd_line.iloc[-1]) if not macd_line.empty else None
    summary.macd_signal = float(macd_sig.iloc[-1]) if not macd_sig.empty else None
    summary.macd_hist = float(macd_hist.iloc[-1]) if not macd_hist.empty else None

    if len(macd_hist) >= 2:
        prev_hist = float(macd_hist.iloc[-2])
        curr_hist = float(macd_hist.iloc[-1])
        if prev_hist < 0 and curr_hist > 0:
            summary.signals.append(TechnicalSignal("MACD", curr_hist, "BUY", 0.8,
                "MACD cruzó línea de señal — BUY"))
        elif prev_hist > 0 and curr_hist < 0:
            summary.signals.append(TechnicalSignal("MACD", curr_hist, "SELL", 0.8,
                "MACD cruzó línea de señal — SELL"))
        elif curr_hist > 0:
            summary.signals.append(TechnicalSignal("MACD", curr_hist, "NEUTRAL", 0.4,
                "MACD positivo — tendencia alcista"))
        else:
            summary.signals.append(TechnicalSignal("MACD", curr_hist, "NEUTRAL", 0.4,
                "MACD negativo — tendencia bajista"))

    # ── Bollinger Bands ───────────────────────────────────────────────────────
    bb_upper, bb_mid, bb_lower = _bollinger(close)
    summary.bb_upper = float(bb_upper.iloc[-1]) if not bb_upper.empty else None
    summary.bb_middle = float(bb_mid.iloc[-1]) if not bb_mid.empty else None
    summary.bb_lower = float(bb_lower.iloc[-1]) if not bb_lower.empty else None

    if summary.bb_upper and summary.bb_lower:
        band_width = summary.bb_upper - summary.bb_lower
        if band_width > 0:
            summary.bb_pct = (current_price - summary.bb_lower) / band_width
        if current_price < summary.bb_lower:
            summary.signals.append(TechnicalSignal("BB", current_price, "BUY", 0.75,
                f"Precio bajo banda inferior BB — BUY"))
        elif current_price > summary.bb_upper:
            summary.signals.append(TechnicalSignal("BB", current_price, "SELL", 0.75,
                f"Precio sobre banda superior BB — SELL"))
        else:
            summary.signals.append(TechnicalSignal("BB", current_price, "NEUTRAL", 0.2,
                f"Precio dentro de BB ({summary.bb_pct:.1%})"))

    # ── EMAs ──────────────────────────────────────────────────────────────────
    ema20 = _ema(close, 20)
    ema50 = _ema(close, 50)
    ema200 = _ema(close, 200)
    summary.ema_20 = float(ema20.iloc[-1]) if not ema20.empty else None
    summary.ema_50 = float(ema50.iloc[-1]) if not ema50.empty else None
    summary.ema_200 = float(ema200.iloc[-1]) if len(ema200.dropna()) > 0 else None

    if summary.ema_20 and summary.ema_50 and len(ema20) >= 2:
        prev_20, curr_20 = float(ema20.iloc[-2]), float(ema20.iloc[-1])
        prev_50, curr_50 = float(ema50.iloc[-2]), float(ema50.iloc[-1])
        if prev_20 < prev_50 and curr_20 > curr_50:
            summary.signals.append(TechnicalSignal("EMA20x50", curr_20, "BUY", 0.85,
                "Golden Cross EMA20/50 — BUY fuerte"))
        elif prev_20 > prev_50 and curr_20 < curr_50:
            summary.signals.append(TechnicalSignal("EMA20x50", curr_20, "SELL", 0.85,
                "Death Cross EMA20/50 — SELL fuerte"))
        elif curr_20 > curr_50:
            summary.signals.append(TechnicalSignal("EMA20x50", curr_20, "NEUTRAL", 0.35,
                "EMA20 > EMA50 — tendencia alcista"))
        else:
            summary.signals.append(TechnicalSignal("EMA20x50", curr_20, "NEUTRAL", 0.35,
                "EMA20 < EMA50 — tendencia bajista"))

    # "Golden Cross" de largo plazo
    if summary.ema_50 and summary.ema_200:
        if summary.ema_50 > summary.ema_200:
            summary.signals.append(TechnicalSignal("EMA50x200", summary.ema_50, "BUY", 0.5,
                "EMA50 > EMA200 — tendencia alcista de largo plazo"))
        else:
            summary.signals.append(TechnicalSignal("EMA50x200", summary.ema_50, "SELL", 0.5,
                "EMA50 < EMA200 — tendencia bajista de largo plazo"))

    # ── SMAs ──────────────────────────────────────────────────────────────────
    sma20 = _sma(close, 20)
    sma50 = _sma(close, 50)
    summary.sma_20 = float(sma20.iloc[-1]) if not sma20.dropna().empty else None
    summary.sma_50 = float(sma50.iloc[-1]) if not sma50.dropna().empty else None

    # ── Estocástico ───────────────────────────────────────────────────────────
    stoch_k, stoch_d = _stochastic(high, low, close)
    summary.stoch_k = float(stoch_k.iloc[-1]) if not stoch_k.empty else None
    summary.stoch_d = float(stoch_d.iloc[-1]) if not stoch_d.empty else None

    if summary.stoch_k is not None and summary.stoch_d is not None:
        if summary.stoch_k < 20 and summary.stoch_d < 20:
            summary.signals.append(TechnicalSignal("Stochastic", summary.stoch_k, "BUY", 0.65,
                f"Estocástico K={summary.stoch_k:.0f} — Zona de sobreventa"))
        elif summary.stoch_k > 80 and summary.stoch_d > 80:
            summary.signals.append(TechnicalSignal("Stochastic", summary.stoch_k, "SELL", 0.65,
                f"Estocástico K={summary.stoch_k:.0f} — Zona de sobrecompra"))

    # ── ATR ───────────────────────────────────────────────────────────────────
    atr_series = _atr(high, low, close)
    summary.atr = float(atr_series.iloc[-1]) if not atr_series.empty else None

    # ── OBV ───────────────────────────────────────────────────────────────────
    if not volume.empty:
        obv_series = _obv(close, volume)
        summary.obv = float(obv_series.iloc[-1]) if not obv_series.empty else None

    # ── ADX ───────────────────────────────────────────────────────────────────
    adx_series = _adx(high, low, close)
    summary.adx = float(adx_series.iloc[-1]) if not adx_series.dropna().empty else None

    # ── CCI ───────────────────────────────────────────────────────────────────
    cci_series = _cci(high, low, close)
    summary.cci = float(cci_series.iloc[-1]) if not cci_series.empty else None

    # ── Williams %R ───────────────────────────────────────────────────────────
    highest_high = high.rolling(14).max()
    lowest_low = low.rolling(14).min()
    wr = -100 * (highest_high - close) / (highest_high - lowest_low + 1e-10)
    summary.williams_r = float(wr.iloc[-1]) if not wr.empty else None

    # ── Soporte / Resistencia ─────────────────────────────────────────────────
    support, resistance = _support_resistance(close)
    summary.support = support
    summary.resistance = resistance

    # ── Señal global ponderada ────────────────────────────────────────────────
    for sig in summary.signals:
        if sig.signal == "BUY":
            summary.buy_score += 1
        elif sig.signal == "SELL":
            summary.sell_score += 1
        else:
            summary.neutral_score += 1

    total = summary.buy_score + summary.sell_score + summary.neutral_score
    if total > 0:
        buy_ratio = summary.buy_score / total
        sell_ratio = summary.sell_score / total
        if buy_ratio >= 0.5:
            summary.overall_signal = "BUY"
        elif sell_ratio >= 0.5:
            summary.overall_signal = "SELL"
        else:
            summary.overall_signal = "NEUTRAL"

    return summary


def signal_color(signal: str) -> str:
    """Retorna color Rich para una señal."""
    return {"BUY": "green", "SELL": "red", "NEUTRAL": "yellow"}.get(signal, "white")


def signal_emoji(signal: str) -> str:
    return {"BUY": "▲ COMPRAR", "SELL": "▼ VENDER", "NEUTRAL": "◆ NEUTRO"}.get(signal, "◆")


def score_bar(buy: int, sell: int, neutral: int, width: int = 20) -> str:
    """Genera barra visual de buy/sell/neutral."""
    total = buy + sell + neutral
    if total == 0:
        return "─" * width
    b = int(buy / total * width)
    s = int(sell / total * width)
    n = width - b - s
    return "█" * b + "░" * n + "▓" * s
