"""
Motor estadístico de predicción.
Implementa: regresión lineal, Monte Carlo, reconocimiento de patrones,
análisis de ciclos, bandas de confianza y score ponderado final.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional
import numpy as np
import pandas as pd
from scipy import stats
from scipy.signal import find_peaks


@dataclass
class PredictionResult:
    symbol: str
    current_price: float
    # Regresión lineal
    trend_direction: str        # "ALCISTA" | "BAJISTA" | "LATERAL"
    trend_slope: float          # puntos por día
    trend_r2: float             # bondad de ajuste (0-1)
    trend_target_5d: float      # objetivo precio a 5 días
    trend_target_20d: float     # objetivo a 20 días
    trend_target_60d: float     # objetivo a 60 días
    # Monte Carlo
    mc_low_5d: float            # percentil 10 a 5 días
    mc_median_5d: float
    mc_high_5d: float           # percentil 90 a 5 días
    mc_low_20d: float
    mc_median_20d: float
    mc_high_20d: float
    # Análisis estadístico
    daily_volatility: float     # desv. est. de retornos diarios
    annual_volatility: float    # volatilidad anualizada
    sharpe_proxy: float         # retorno_promedio / volatilidad
    # Patrones detectados
    patterns: list[str] = field(default_factory=list)
    # Score final
    stat_signal: str = "NEUTRAL"    # BUY | SELL | NEUTRAL
    confidence: float = 0.5         # 0-1


# ─── Regresión lineal ──────────────────────────────────────────────────────────
def linear_regression_analysis(close: pd.Series) -> dict:
    """Ajusta regresión lineal a los últimos N precios."""
    n = min(60, len(close))
    y = close.tail(n).values.astype(float)
    x = np.arange(n)

    slope, intercept, r_value, p_value, std_err = stats.linregress(x, y)

    # Proyecciones
    last_x = n - 1
    target_5d  = intercept + slope * (last_x + 5)
    target_20d = intercept + slope * (last_x + 20)
    target_60d = intercept + slope * (last_x + 60)

    return {
        "slope": slope,
        "intercept": intercept,
        "r2": r_value ** 2,
        "p_value": p_value,
        "target_5d": target_5d,
        "target_20d": target_20d,
        "target_60d": target_60d,
    }


# ─── Simulación Monte Carlo ────────────────────────────────────────────────────
def monte_carlo_simulation(close: pd.Series, horizon_days: int = 20,
                            n_simulations: int = 1000) -> dict:
    """
    Simulación de Monte Carlo para distribución de precios futuros.
    Basada en Geometric Brownian Motion con parámetros históricos.
    """
    if len(close) < 20:
        p = float(close.iloc[-1])
        return {"low": p*0.95, "median": p, "high": p*1.05,
                "p10": p*0.95, "p25": p*0.97, "p75": p*1.03, "p90": p*1.05}

    returns = close.pct_change().dropna()
    mu = float(returns.mean())
    sigma = float(returns.std())
    S0 = float(close.iloc[-1])

    rng = np.random.default_rng(42)
    dt = 1
    paths = np.zeros((n_simulations, horizon_days + 1))
    paths[:, 0] = S0

    for t in range(1, horizon_days + 1):
        Z = rng.standard_normal(n_simulations)
        paths[:, t] = paths[:, t-1] * np.exp(
            (mu - 0.5 * sigma**2) * dt + sigma * np.sqrt(dt) * Z
        )

    final_prices = paths[:, -1]
    return {
        "low":    float(np.percentile(final_prices, 10)),
        "p25":    float(np.percentile(final_prices, 25)),
        "median": float(np.percentile(final_prices, 50)),
        "p75":    float(np.percentile(final_prices, 75)),
        "high":   float(np.percentile(final_prices, 90)),
        "mean":   float(np.mean(final_prices)),
        "std":    float(np.std(final_prices)),
    }


# ─── Reconocimiento de patrones ────────────────────────────────────────────────
def detect_patterns(close: pd.Series) -> list[str]:
    """
    Detecta patrones clásicos de análisis técnico.
    Retorna lista de strings con descripciones.
    """
    patterns = []
    if len(close) < 30:
        return patterns

    prices = close.values.astype(float)

    # Máximos y mínimos locales
    peaks, _ = find_peaks(prices, distance=5)
    troughs, _ = find_peaks(-prices, distance=5)

    if len(peaks) >= 2 and len(troughs) >= 1:
        last_two_peaks = prices[peaks[-2:]]
        peak_diff_pct = abs(last_two_peaks[1] - last_two_peaks[0]) / last_two_peaks[0]

        # Doble Techo
        if peak_diff_pct < 0.03 and prices[-1] < prices[peaks[-1]] * 0.97:
            patterns.append("⚠ Doble Techo (bajista)")

    if len(troughs) >= 2 and len(peaks) >= 1:
        last_two_troughs = prices[troughs[-2:]]
        trough_diff_pct = abs(last_two_troughs[1] - last_two_troughs[0]) / last_two_troughs[0]

        # Doble Suelo
        if trough_diff_pct < 0.03 and prices[-1] > prices[troughs[-1]] * 1.03:
            patterns.append("✓ Doble Suelo (alcista)")

    # Cabeza y Hombros (Head & Shoulders)
    if len(peaks) >= 3:
        p1 = prices[peaks[-3]]
        p2 = prices[peaks[-2]]  # cabeza (debería ser el más alto)
        p3 = prices[peaks[-1]]
        shoulder_avg = (p1 + p3) / 2
        if p2 > shoulder_avg * 1.02 and abs(p1 - p3) / shoulder_avg < 0.04:
            if prices[-1] < shoulder_avg * 0.98:
                patterns.append("⚠ Cabeza y Hombros (bajista)")

    # Cabeza y Hombros Invertido
    if len(troughs) >= 3:
        t1 = prices[troughs[-3]]
        t2 = prices[troughs[-2]]  # cabeza (debería ser el más bajo)
        t3 = prices[troughs[-1]]
        shoulder_avg = (t1 + t3) / 2
        if t2 < shoulder_avg * 0.98 and abs(t1 - t3) / shoulder_avg < 0.04:
            if prices[-1] > shoulder_avg * 1.02:
                patterns.append("✓ HH Invertida (alcista)")

    # Tendencia alcista (higher highs + higher lows)
    if len(peaks) >= 2 and len(troughs) >= 2:
        hh = prices[peaks[-1]] > prices[peaks[-2]]
        hl = prices[troughs[-1]] > prices[troughs[-2]]
        lh = prices[peaks[-1]] < prices[peaks[-2]]
        ll = prices[troughs[-1]] < prices[troughs[-2]]

        if hh and hl:
            patterns.append("↑ Tendencia Alcista Confirmada")
        elif lh and ll:
            patterns.append("↓ Tendencia Bajista Confirmada")

    # Triángulo ascendente (resistencia plana, soporte sube)
    if len(peaks) >= 3 and len(troughs) >= 3:
        peak_slope = np.polyfit(range(3), [prices[p] for p in peaks[-3:]], 1)[0]
        trough_slope = np.polyfit(range(3), [prices[t] for t in troughs[-3:]], 1)[0]
        if abs(peak_slope) < 0.001 * prices[-1] and trough_slope > 0:
            patterns.append("△ Triángulo Ascendente (alcista)")
        elif abs(trough_slope) < 0.001 * prices[-1] and peak_slope < 0:
            patterns.append("▽ Triángulo Descendente (bajista)")

    # Análisis de momentum de precio
    returns_20d = (prices[-1] / prices[-21] - 1) if len(prices) >= 21 else None
    returns_5d = (prices[-1] / prices[-6] - 1) if len(prices) >= 6 else None

    if returns_20d is not None and returns_5d is not None:
        if returns_20d > 0.1:
            patterns.append(f"🚀 Momentum fuerte +{returns_20d:.1%} (20d)")
        elif returns_20d < -0.1:
            patterns.append(f"📉 Caída fuerte {returns_20d:.1%} (20d)")

    # Compresión de volatilidad (posible ruptura inminente)
    std_recent = np.std(prices[-10:])
    std_prev = np.std(prices[-30:-10])
    if std_prev > 0 and (std_recent / std_prev) < 0.5:
        patterns.append("⚡ Compresión de Volatilidad (ruptura inminente)")

    return patterns if patterns else ["◆ Sin patrones claros detectados"]


# ─── Análisis de ciclos ────────────────────────────────────────────────────────
def detect_seasonality(close: pd.Series) -> dict:
    """Analiza si hay estacionalidad o ciclos en los retornos."""
    if len(close) < 60:
        return {}

    returns = close.pct_change().dropna()

    # Autocorrelación a 5 y 20 días
    acf_5 = float(returns.autocorr(lag=5)) if len(returns) > 10 else 0
    acf_20 = float(returns.autocorr(lag=20)) if len(returns) > 25 else 0

    # Skewness y curtosis de retornos
    skew = float(stats.skew(returns))
    kurt = float(stats.kurtosis(returns))

    return {
        "autocorr_5d": acf_5,
        "autocorr_20d": acf_20,
        "skewness": skew,
        "kurtosis": kurt,
        "fat_tails": kurt > 3,  # colas pesadas (riesgo de movimientos extremos)
    }


# ─── Score ponderado ───────────────────────────────────────────────────────────
def weighted_stat_signal(trend_slope: float, r2: float,
                          mc_median: float, current: float,
                          patterns: list[str]) -> tuple[str, float]:
    """
    Combina múltiples señales estadísticas en un score final ponderado.
    """
    score = 0.0  # positivo = alcista, negativo = bajista
    max_score = 0.0

    # Regresión (peso 40%)
    if r2 > 0.3:
        direction = 1 if trend_slope > 0 else -1
        score += direction * r2 * 40
        max_score += 40

    # Monte Carlo (peso 35%)
    if current > 0:
        mc_upside = (mc_median - current) / current
        score += np.clip(mc_upside * 100, -35, 35)
        max_score += 35

    # Patrones (peso 25%)
    bullish_patterns = sum(1 for p in patterns if any(w in p for w in ["✓", "alcista", "↑", "🚀", "△"]))
    bearish_patterns = sum(1 for p in patterns if any(w in p for w in ["⚠", "bajista", "↓", "📉", "▽"]))
    pattern_score = (bullish_patterns - bearish_patterns) * 8.33
    score += np.clip(pattern_score, -25, 25)
    max_score += 25

    if max_score == 0:
        return "NEUTRAL", 0.5

    normalized = score / max_score  # -1 a 1

    if normalized > 0.2:
        signal = "BUY"
        confidence = 0.5 + (normalized * 0.5)
    elif normalized < -0.2:
        signal = "SELL"
        confidence = 0.5 + (abs(normalized) * 0.5)
    else:
        signal = "NEUTRAL"
        confidence = 0.5

    return signal, min(confidence, 0.99)


# ─── Función principal ─────────────────────────────────────────────────────────
def full_analysis(df: pd.DataFrame, symbol: str = "") -> PredictionResult:
    """Ejecuta análisis estadístico completo sobre datos históricos."""
    if df.empty or len(df) < 20:
        p = 0.0
        return PredictionResult(
            symbol=symbol, current_price=p,
            trend_direction="N/A", trend_slope=0, trend_r2=0,
            trend_target_5d=p, trend_target_20d=p, trend_target_60d=p,
            mc_low_5d=p, mc_median_5d=p, mc_high_5d=p,
            mc_low_20d=p, mc_median_20d=p, mc_high_20d=p,
            daily_volatility=0, annual_volatility=0, sharpe_proxy=0,
        )

    close = df["Close"].astype(float).squeeze()
    current_price = float(close.iloc[-1])

    # Regresión
    reg = linear_regression_analysis(close)
    slope = reg["slope"]
    if abs(slope) < 0.001 * current_price:
        trend_dir = "LATERAL"
    elif slope > 0:
        trend_dir = "ALCISTA"
    else:
        trend_dir = "BAJISTA"

    # Monte Carlo 5 y 20 días
    mc5 = monte_carlo_simulation(close, horizon_days=5)
    mc20 = monte_carlo_simulation(close, horizon_days=20)

    # Volatilidad
    returns = close.pct_change().dropna()
    daily_vol = float(returns.std())
    annual_vol = daily_vol * np.sqrt(252)
    mean_return = float(returns.mean())
    sharpe = (mean_return / daily_vol * np.sqrt(252)) if daily_vol > 0 else 0

    # Patrones
    patterns = detect_patterns(close)

    # Score final
    stat_signal, confidence = weighted_stat_signal(
        slope, reg["r2"], mc20["median"], current_price, patterns
    )

    return PredictionResult(
        symbol=symbol,
        current_price=current_price,
        trend_direction=trend_dir,
        trend_slope=slope,
        trend_r2=reg["r2"],
        trend_target_5d=reg["target_5d"],
        trend_target_20d=reg["target_20d"],
        trend_target_60d=reg["target_60d"],
        mc_low_5d=mc5["low"],
        mc_median_5d=mc5["median"],
        mc_high_5d=mc5["high"],
        mc_low_20d=mc20["low"],
        mc_median_20d=mc20["median"],
        mc_high_20d=mc20["high"],
        daily_volatility=daily_vol,
        annual_volatility=annual_vol,
        sharpe_proxy=sharpe,
        patterns=patterns,
        stat_signal=stat_signal,
        confidence=confidence,
    )


def trend_arrow(direction: str) -> str:
    return {"ALCISTA": "▲", "BAJISTA": "▼", "LATERAL": "◆"}.get(direction, "?")


def confidence_bar(conf: float, width: int = 10) -> str:
    filled = int(conf * width)
    return "█" * filled + "░" * (width - filled)
