import json
import os
from pathlib import Path

CONFIG_DIR = Path.home() / ".bloomberg_terminal"
CONFIG_FILE = CONFIG_DIR / "config.json"
ALGO_FILE = CONFIG_DIR / "algorithms.json"

DEFAULT_CONFIG = {
    "banxico_token": "",  # Registrate gratis en https://www.banxico.org.mx/SieAPIRest/service/v1/token
    "refresh_interval": 45,
    "watchlist_us": [
        "AAPL", "MSFT", "GOOGL", "AMZN", "TSLA",
        "NVDA", "META", "JPM", "BAC", "XOM",
        "WMT", "V", "MA", "UNH", "HD"
    ],
    "watchlist_mx": [
        "AMXL.MX", "WALMEX.MX", "FEMSA.MX", "GFNORTEO.MX",
        "BIMBOA.MX", "TLEVISACPO.MX", "ALSEA.MX", "GMEXICOB.MX",
        "PINFRA.MX", "KOFUBL.MX"
    ],
    "custom_tickers": [],
}

DEFAULT_ALGORITHMS = [
    {
        "name": "RSI Extremos",
        "description": "Compra en sobreventa, vende en sobrecompra",
        "enabled": True,
        "logic": "ANY",
        "rules": [
            {"indicator": "RSI", "condition": "below", "value": 30, "signal": "BUY", "weight": 1.0},
            {"indicator": "RSI", "condition": "above", "value": 70, "signal": "SELL", "weight": 1.0},
        ]
    },
    {
        "name": "MACD Cruce",
        "description": "Señal basada en cruce de MACD",
        "enabled": True,
        "logic": "ANY",
        "rules": [
            {"indicator": "MACD", "condition": "cross_up", "value": 0, "signal": "BUY", "weight": 1.5},
            {"indicator": "MACD", "condition": "cross_down", "value": 0, "signal": "SELL", "weight": 1.5},
        ]
    },
    {
        "name": "Bollinger Rebote",
        "description": "Compra en banda inferior, vende en banda superior",
        "enabled": True,
        "logic": "ANY",
        "rules": [
            {"indicator": "BB_LOWER", "condition": "price_below", "value": 0, "signal": "BUY", "weight": 1.2},
            {"indicator": "BB_UPPER", "condition": "price_above", "value": 0, "signal": "SELL", "weight": 1.2},
        ]
    },
    {
        "name": "Momentum Combinado",
        "description": "Confluencia de múltiples señales alcistas/bajistas",
        "enabled": True,
        "logic": "ALL",
        "rules": [
            {"indicator": "RSI", "condition": "below", "value": 45, "signal": "BUY", "weight": 1.0},
            {"indicator": "MACD", "condition": "cross_up", "value": 0, "signal": "BUY", "weight": 1.0},
            {"indicator": "EMA20_50", "condition": "cross_up", "value": 0, "signal": "BUY", "weight": 1.0},
        ]
    }
]

# ─── Símbolos del mercado ──────────────────────────────────────────────────────
INDICES = {
    "^GSPC":    "S&P 500",
    "^DJI":     "Dow Jones",
    "^IXIC":    "NASDAQ",
    "^MXX":     "IPC México",
    "^N225":    "Nikkei 225",
    "000001.SS":"Shanghai SSE",
    "^HSI":     "Hang Seng",
    "^FTSE":    "FTSE 100",
    "^GDAXI":   "DAX",
}

CRYPTO = {
    "BTC-USD": "Bitcoin",
    "ETH-USD": "Ethereum",
    "BNB-USD": "BNB",
    "SOL-USD": "Solana",
}

COMMODITIES = {
    "GC=F":  "Oro (Gold)",
    "SI=F":  "Plata (Silver)",
    "CL=F":  "WTI Crude Oil",
    "BZ=F":  "Brent Crude Oil",
    "NG=F":  "Natural Gas",
    "HG=F":  "Cobre",
}

FOREX = {
    "MXN=X":    "USD/MXN",
    "EURUSD=X": "EUR/USD",
    "GBPUSD=X": "GBP/USD",
    "JPYUSD=X": "JPY/USD",
}

# Series del Banco de México (SIE)
BANXICO_SERIES = {
    "SF43936": "CETES 28 días",
    "SF43939": "CETES 91 días",
    "SF43942": "CETES 182 días",
    "SF43945": "CETES 364 días",
    "SF63528": "Tipo de cambio USD/MXN (FIX)",
    "SF46410": "TIIE 28 días",
    "SF60632": "Inflación anual",
}


def load_config() -> dict:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE) as f:
                saved = json.load(f)
            cfg = DEFAULT_CONFIG.copy()
            cfg.update(saved)
            return cfg
        except Exception:
            pass
    save_config(DEFAULT_CONFIG)
    return DEFAULT_CONFIG.copy()


def save_config(config: dict):
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_FILE, "w") as f:
        json.dump(config, f, indent=2)


def load_algorithms() -> list:
    if ALGO_FILE.exists():
        try:
            with open(ALGO_FILE) as f:
                return json.load(f)
        except Exception:
            pass
    save_algorithms(DEFAULT_ALGORITHMS)
    return DEFAULT_ALGORITHMS.copy()


def save_algorithms(algorithms: list):
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with open(ALGO_FILE, "w") as f:
        json.dump(algorithms, f, indent=2)
