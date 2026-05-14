"""
Motor de algoritmos personalizados de trading.
El usuario define reglas en JSON; este módulo las evalúa sobre indicadores técnicos.
Soporta backtesting básico para validar estrategias.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional
import numpy as np
import pandas as pd

from bloomberg.technical_analysis import TechnicalSummary, analyze
from bloomberg.config import load_algorithms, save_algorithms


@dataclass
class AlgoResult:
    algorithm_name: str
    signal: str                  # BUY | SELL | HOLD
    triggered_rules: list[str]
    score: float                 # -1 (strong sell) a +1 (strong buy)
    confidence: float            # 0-1


@dataclass
class BacktestResult:
    algorithm_name: str
    symbol: str
    period: str
    total_trades: int
    winning_trades: int
    losing_trades: int
    win_rate: float
    total_return: float
    max_drawdown: float
    sharpe: float
    trades: list[dict] = field(default_factory=list)


# ─── Evaluación de condiciones ────────────────────────────────────────────────
def _get_indicator_value(rule: dict, ta: TechnicalSummary, current_price: float,
                          prev_ta: Optional[TechnicalSummary] = None) -> Optional[float]:
    ind = rule.get("indicator", "").upper()
    mapping = {
        "RSI":      ta.rsi,
        "MACD":     ta.macd_hist,
        "BB_UPPER": ta.bb_upper,
        "BB_LOWER": ta.bb_lower,
        "BB_PCT":   ta.bb_pct,
        "EMA20":    ta.ema_20,
        "EMA50":    ta.ema_50,
        "EMA200":   ta.ema_200,
        "SMA20":    ta.sma_20,
        "SMA50":    ta.sma_50,
        "STOCH_K":  ta.stoch_k,
        "STOCH_D":  ta.stoch_d,
        "ADX":      ta.adx,
        "CCI":      ta.cci,
        "WILLIAMS": ta.williams_r,
        "PRICE":    current_price,
        "ATR":      ta.atr,
    }
    return mapping.get(ind)


def _evaluate_condition(rule: dict, ta: TechnicalSummary, current_price: float,
                         df: Optional[pd.DataFrame] = None) -> tuple[bool, str]:
    """
    Evalúa una regla individual. Retorna (triggered: bool, description: str).
    """
    ind = rule.get("indicator", "").upper()
    condition = rule.get("condition", "").lower()
    threshold = rule.get("value", 0)
    signal = rule.get("signal", "HOLD")

    val = _get_indicator_value(rule, ta, current_price)

    if val is None:
        return False, f"{ind}: dato no disponible"

    triggered = False
    desc = ""

    if condition == "above":
        triggered = val > threshold
        desc = f"{ind}={val:.2f} > {threshold} → {signal}"

    elif condition == "below":
        triggered = val < threshold
        desc = f"{ind}={val:.2f} < {threshold} → {signal}"

    elif condition == "between":
        lo, hi = threshold, rule.get("value2", threshold)
        triggered = lo <= val <= hi
        desc = f"{ind}={val:.2f} entre [{lo},{hi}] → {signal}"

    elif condition in ("cross_up", "golden_cross"):
        if df is not None and len(df) >= 2:
            from bloomberg.technical_analysis import _ema, _rsi, _macd
            close = df["Close"].astype(float).squeeze()
            if ind in ("MACD", "MACD_HIST"):
                ml, ms, mh = _macd(close)
                if len(mh) >= 2:
                    triggered = float(mh.iloc[-2]) < 0 and float(mh.iloc[-1]) > 0
            elif ind in ("EMA20_50", "EMA20X50"):
                ema20 = _ema(close, 20)
                ema50 = _ema(close, 50)
                if len(ema20) >= 2:
                    triggered = (float(ema20.iloc[-2]) < float(ema50.iloc[-2]) and
                                 float(ema20.iloc[-1]) > float(ema50.iloc[-1]))
        desc = f"{ind} cruzó hacia arriba → {signal}"

    elif condition in ("cross_down", "death_cross"):
        if df is not None and len(df) >= 2:
            from bloomberg.technical_analysis import _ema, _macd
            close = df["Close"].astype(float).squeeze()
            if ind in ("MACD", "MACD_HIST"):
                ml, ms, mh = _macd(close)
                if len(mh) >= 2:
                    triggered = float(mh.iloc[-2]) > 0 and float(mh.iloc[-1]) < 0
            elif ind in ("EMA20_50", "EMA20X50"):
                ema20 = _ema(close, 20)
                ema50 = _ema(close, 50)
                if len(ema20) >= 2:
                    triggered = (float(ema20.iloc[-2]) > float(ema50.iloc[-2]) and
                                 float(ema20.iloc[-1]) < float(ema50.iloc[-1]))
        desc = f"{ind} cruzó hacia abajo → {signal}"

    elif condition == "price_below":
        # Precio bajo banda / nivel
        if ind == "BB_LOWER" and ta.bb_lower:
            triggered = current_price < ta.bb_lower
            desc = f"Precio {current_price:.2f} < BB_LOWER {ta.bb_lower:.2f} → {signal}"
        else:
            triggered = current_price < val
            desc = f"Precio {current_price:.2f} < {ind}={val:.2f} → {signal}"

    elif condition == "price_above":
        if ind == "BB_UPPER" and ta.bb_upper:
            triggered = current_price > ta.bb_upper
            desc = f"Precio {current_price:.2f} > BB_UPPER {ta.bb_upper:.2f} → {signal}"
        else:
            triggered = current_price > val
            desc = f"Precio {current_price:.2f} > {ind}={val:.2f} → {signal}"

    return triggered, desc


def evaluate_algorithm(algo: dict, ta: TechnicalSummary,
                        current_price: float,
                        df: Optional[pd.DataFrame] = None) -> AlgoResult:
    """Evalúa un algoritmo completo sobre los indicadores actuales."""
    rules = algo.get("rules", [])
    logic = algo.get("logic", "ANY").upper()  # ANY | ALL
    name = algo.get("name", "Sin nombre")

    if not rules:
        return AlgoResult(name, "HOLD", [], 0.0, 0.0)

    triggered_buy = []
    triggered_sell = []
    all_results = []

    for rule in rules:
        fired, desc = _evaluate_condition(rule, ta, current_price, df)
        all_results.append((fired, desc, rule.get("signal", "HOLD"), rule.get("weight", 1.0)))

    if logic == "ALL":
        # Todas las reglas deben cumplirse para el mismo signal
        buy_rules = [r for r in all_results if r[2] == "BUY"]
        sell_rules = [r for r in all_results if r[2] == "SELL"]
        buy_triggered = all(r[0] for r in buy_rules) if buy_rules else False
        sell_triggered = all(r[0] for r in sell_rules) if sell_rules else False
        if buy_triggered:
            triggered_buy = [r[1] for r in buy_rules]
        if sell_triggered:
            triggered_sell = [r[1] for r in sell_rules]
    else:  # ANY
        for fired, desc, sig, weight in all_results:
            if fired:
                if sig == "BUY":
                    triggered_buy.append(desc)
                elif sig == "SELL":
                    triggered_sell.append(desc)

    # Score ponderado
    buy_weight = sum(r[3] for r in all_results if r[0] and r[2] == "BUY")
    sell_weight = sum(r[3] for r in all_results if r[0] and r[2] == "SELL")
    total_weight = sum(r[3] for r in all_results)
    score = (buy_weight - sell_weight) / (total_weight + 1e-10)

    if triggered_buy and not triggered_sell:
        signal = "BUY"
        conf = min(buy_weight / (total_weight + 1e-10), 1.0)
    elif triggered_sell and not triggered_buy:
        signal = "SELL"
        conf = min(sell_weight / (total_weight + 1e-10), 1.0)
    elif triggered_buy and triggered_sell:
        signal = "BUY" if buy_weight >= sell_weight else "SELL"
        conf = 0.4
    else:
        signal = "HOLD"
        conf = 0.5

    all_triggered = triggered_buy + triggered_sell
    return AlgoResult(name, signal, all_triggered, float(score), float(conf))


def evaluate_all_algorithms(ta: TechnicalSummary, current_price: float,
                              df: Optional[pd.DataFrame] = None) -> list[AlgoResult]:
    """Evalúa todos los algoritmos habilitados."""
    algos = load_algorithms()
    results = []
    for algo in algos:
        if not algo.get("enabled", True):
            continue
        result = evaluate_algorithm(algo, ta, current_price, df)
        results.append(result)
    return results


def aggregate_algo_signals(results: list[AlgoResult]) -> tuple[str, float]:
    """
    Combina señales de todos los algoritmos en un consenso.
    Retorna (signal, confidence).
    """
    if not results:
        return "HOLD", 0.5

    buy_score = sum(r.confidence for r in results if r.signal == "BUY")
    sell_score = sum(r.confidence for r in results if r.signal == "SELL")
    hold_score = sum(r.confidence for r in results if r.signal == "HOLD")
    total = len(results)

    if buy_score > sell_score and buy_score > hold_score:
        conf = buy_score / total
        return "BUY", min(conf, 0.99)
    elif sell_score > buy_score and sell_score > hold_score:
        conf = sell_score / total
        return "SELL", min(conf, 0.99)
    return "HOLD", 0.5


# ─── Backtesting básico ────────────────────────────────────────────────────────
def backtest_algorithm(algo: dict, df: pd.DataFrame, symbol: str = "") -> BacktestResult:
    """
    Backtesting sencillo de una estrategia sobre datos históricos.
    Usa señales diarias de los indicadores técnicos.
    """
    name = algo.get("name", "Sin nombre")
    if df.empty or len(df) < 40:
        return BacktestResult(name, symbol, "N/A", 0, 0, 0, 0, 0, 0, 0)

    close = df["Close"].astype(float).squeeze()
    n = len(df)

    # Calcular indicadores para cada punto (ventana deslizante)
    trades = []
    position = None  # None | {"entry": price, "date": date}
    equity = [10000.0]
    equity_val = 10000.0
    shares = 0

    for i in range(40, n):
        sub_df = df.iloc[:i+1].copy()
        ta = analyze(sub_df, symbol)
        current = float(close.iloc[i])
        result = evaluate_algorithm(algo, ta, current, sub_df)

        if result.signal == "BUY" and position is None:
            shares = equity_val / current
            position = {"entry": current, "date": df.index[i], "shares": shares}

        elif result.signal == "SELL" and position is not None:
            exit_price = current
            pnl = (exit_price - position["entry"]) * position["shares"]
            equity_val += pnl
            trades.append({
                "entry": position["entry"],
                "exit": exit_price,
                "pnl": pnl,
                "pnl_pct": (exit_price / position["entry"] - 1) * 100,
                "entry_date": str(position["date"])[:10],
                "exit_date": str(df.index[i])[:10],
            })
            position = None

        equity.append(equity_val)

    # Si quedó posición abierta, cerrar al último precio
    if position is not None:
        last_price = float(close.iloc[-1])
        pnl = (last_price - position["entry"]) * position["shares"]
        equity_val += pnl
        trades.append({
            "entry": position["entry"],
            "exit": last_price,
            "pnl": pnl,
            "pnl_pct": (last_price / position["entry"] - 1) * 100,
            "entry_date": str(position["date"])[:10],
            "exit_date": "abierto",
        })

    total = len(trades)
    winners = sum(1 for t in trades if t["pnl"] > 0)
    win_rate = (winners / total) if total else 0
    total_return = (equity_val / 10000 - 1) * 100

    # Max drawdown
    equity_arr = np.array(equity)
    rolling_max = np.maximum.accumulate(equity_arr)
    drawdowns = (equity_arr - rolling_max) / (rolling_max + 1e-10)
    max_dd = float(drawdowns.min()) * 100

    # Sharpe aproximado
    if len(equity) > 1:
        eq_returns = np.diff(equity) / (np.array(equity[:-1]) + 1e-10)
        sharpe = float(np.mean(eq_returns) / (np.std(eq_returns) + 1e-10) * np.sqrt(252))
    else:
        sharpe = 0

    return BacktestResult(
        algorithm_name=name,
        symbol=symbol,
        period=f"{n} días",
        total_trades=total,
        winning_trades=winners,
        losing_trades=total - winners,
        win_rate=win_rate,
        total_return=total_return,
        max_drawdown=max_dd,
        sharpe=sharpe,
        trades=trades[-10:],  # últimos 10 trades
    )
