"""
Bloomberg Terminal Personal — Interfaz TUI principal.
Construida con Textual. Diseño inspirado en Bloomberg Terminal.
"""
from __future__ import annotations

import sys
import threading
import time
from datetime import datetime
from typing import Optional

import numpy as np
import pandas as pd
import pytz

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical, ScrollableContainer
from textual.reactive import reactive
from textual.widgets import (
    DataTable, Footer, Header, Input, Label,
    Static, TabPane, TabbedContent, Button, Select, TextArea, Rule,
)
from textual import work
from rich.text import Text
from rich.table import Table
from rich.panel import Panel
from rich.console import Console
from rich.style import Style

from bloomberg.config import (
    load_config, save_config, load_algorithms, save_algorithms,
    INDICES, CRYPTO, COMMODITIES, FOREX,
)
from bloomberg.data_fetcher import (
    get_quotes_bulk, get_quote, get_history, get_company_info,
    get_correlation_matrix, fmt_price, fmt_change, fmt_market_cap, fmt_volume,
    is_market_open,
)
from bloomberg.banxico_api import get_all_banxico_data, get_cetes_summary, get_tipo_cambio
from bloomberg.news_fetcher import get_latest_news, get_ticker_news, fmt_news_age
from bloomberg.technical_analysis import analyze, signal_color, signal_emoji, score_bar
from bloomberg.statistical_engine import full_analysis, trend_arrow, confidence_bar
from bloomberg.algorithm_engine import (
    evaluate_all_algorithms, aggregate_algo_signals,
    backtest_algorithm, evaluate_algorithm,
)

# ─── Constantes de estilo Bloomberg ──────────────────────────────────────────
BG = "on #0a0a0a"
ORANGE = "#ff8c00"
GREEN = "#00ff41"
RED = "#ff3333"
CYAN = "#00d4ff"
YELLOW = "#ffd700"
WHITE = "#e8e8e8"
GRAY = "#555555"


def price_color(change_pct: float) -> str:
    if change_pct > 0:
        return GREEN
    elif change_pct < 0:
        return RED
    return WHITE


def colored_price(price: float, change_pct: float) -> Text:
    color = price_color(change_pct)
    arrow = "▲" if change_pct > 0 else ("▼" if change_pct < 0 else "◆")
    t = Text()
    t.append(f"{price:,.2f}", style=f"bold {color}")
    t.append(f" {arrow}{abs(change_pct):.2f}%", style=color)
    return t


# ─── App principal ─────────────────────────────────────────────────────────────
class BloombergApp(App):
    """Bloomberg Terminal Personal."""

    CSS = """
    Screen {
        background: #0a0a0a;
    }
    Header {
        background: #1a0a00;
        color: #ff8c00;
        height: 1;
    }
    Footer {
        background: #1a0a00;
        color: #888888;
        height: 1;
    }
    TabbedContent {
        height: 1fr;
    }
    TabPane {
        padding: 0;
    }
    TabbedContent > Tabs {
        background: #111111;
        height: 2;
    }
    Tab {
        color: #888888;
        padding: 0 1;
    }
    Tab.-active {
        color: #ff8c00;
        background: #1a0a00;
    }
    DataTable {
        background: #0a0a0a;
        color: #e8e8e8;
        height: 1fr;
    }
    DataTable > .datatable--header {
        background: #1a0a00;
        color: #ff8c00;
        text-style: bold;
    }
    DataTable > .datatable--cursor {
        background: #2a1a00;
        color: #ffffff;
    }
    DataTable > .datatable--hover {
        background: #1a1a00;
    }
    Static {
        background: #0a0a0a;
        color: #e8e8e8;
    }
    Label {
        color: #ff8c00;
    }
    Input {
        background: #111111;
        border: solid #333333;
        color: #ffffff;
    }
    Button {
        background: #1a0a00;
        border: solid #ff8c00;
        color: #ff8c00;
    }
    Button:hover {
        background: #2a1000;
    }
    TextArea {
        background: #111111;
        border: solid #333333;
        color: #00ff41;
    }
    .panel-title {
        background: #1a0a00;
        color: #ff8c00;
        text-style: bold;
        padding: 0 1;
        height: 1;
    }
    .section-label {
        color: #ff8c00;
        text-style: bold;
    }
    .status-bar {
        background: #111111;
        color: #888888;
        height: 1;
        padding: 0 1;
    }
    ScrollableContainer {
        background: #0a0a0a;
        scrollbar-color: #333333;
        scrollbar-background: #0a0a0a;
    }
    #detail_panel {
        border: solid #333333;
        padding: 1;
        height: 1fr;
    }
    #chart_panel {
        border: solid #333333;
        height: 20;
    }
    #news_scroll {
        border: solid #333333;
        height: 1fr;
    }
    #algo_rules {
        height: 1fr;
        border: solid #333333;
    }
    """

    BINDINGS = [
        Binding("q", "quit", "Salir", priority=True),
        Binding("r", "refresh_all", "Refrescar"),
        Binding("1", "switch_tab('dashboard')", "Dashboard"),
        Binding("2", "switch_tab('usa')", "USA"),
        Binding("3", "switch_tab('mexico')", "México"),
        Binding("4", "switch_tab('global')", "Global"),
        Binding("5", "switch_tab('analisis')", "Análisis"),
        Binding("6", "switch_tab('prediccion')", "Predicción"),
        Binding("7", "switch_tab('cetes')", "CETES"),
        Binding("8", "switch_tab('noticias')", "Noticias"),
        Binding("9", "switch_tab('algoritmo')", "Algoritmo"),
    ]

    selected_symbol: reactive[str] = reactive("AAPL")
    last_update: reactive[str] = reactive("--:--:--")
    market_status_us: reactive[str] = reactive("...")
    market_status_mx: reactive[str] = reactive("...")

    def __init__(self):
        super().__init__()
        self.config = load_config()
        self._data_lock = threading.Lock()
        self._quotes_us: dict = {}
        self._quotes_mx: dict = {}
        self._quotes_idx: dict = {}
        self._quotes_crypto: dict = {}
        self._quotes_comm: dict = {}
        self._quotes_forex: dict = {}
        self._banxico_data: dict = {}
        self._cetes_data: list = []
        self._news_data: list = []
        self._ta_summary = None
        self._stat_result = None
        self._algo_results: list = []
        self._selected_df = pd.DataFrame()
        self._company_info: dict = {}

    # ─── Composición de la UI ─────────────────────────────────────────────────
    def compose(self) -> ComposeResult:
        yield Header(show_clock=True, name="◆ BLOOMBERG TERMINAL PERSONAL ◆")

        with TabbedContent(initial="dashboard", id="tabs"):

            # ── Tab 1: Dashboard ─────────────────────────────────────────────
            with TabPane("📊 MERCADOS", id="dashboard"):
                with Horizontal():
                    with Vertical(id="left_panel", classes=""):
                        yield Static("── ÍNDICES GLOBALES ──", classes="panel-title")
                        yield DataTable(id="idx_table", show_cursor=True, zebra_stripes=True)
                        yield Static("── CRYPTO ──", classes="panel-title")
                        yield DataTable(id="crypto_table", show_cursor=False, zebra_stripes=True)
                    with Vertical(id="center_panel"):
                        yield Static("── COMMODITIES & FOREX ──", classes="panel-title")
                        yield DataTable(id="comm_table", show_cursor=False, zebra_stripes=True)
                        yield Static("── ÚLTIMAS NOTICIAS ──", classes="panel-title")
                        with ScrollableContainer(id="dash_news"):
                            yield Static("Cargando noticias...", id="dash_news_content")
                    with Vertical(id="right_panel"):
                        yield Static("── BANXICO / CETES ──", classes="panel-title")
                        yield DataTable(id="cetes_dash_table", show_cursor=False, zebra_stripes=True)
                        yield Static("── MARKET STATUS ──", classes="panel-title")
                        yield Static("", id="market_status_panel")

            # ── Tab 2: USA ───────────────────────────────────────────────────
            with TabPane("🇺🇸 USA", id="usa"):
                with Horizontal():
                    with Vertical():
                        yield Static("── BOLSA USA (NYSE/NASDAQ) ──", classes="panel-title")
                        yield DataTable(id="us_table", show_cursor=True, zebra_stripes=True)
                        yield Static("── BUSCAR TICKER ──", classes="panel-title")
                        with Horizontal():
                            yield Input(placeholder="Ej: AAPL, TSLA, SPY...", id="ticker_input")
                            yield Button("Buscar", id="search_btn", variant="primary")
                    with Vertical(id="detail_panel"):
                        yield Static("── DETALLE ──", classes="panel-title")
                        yield Static("Selecciona un ticker", id="detail_content")

            # ── Tab 3: México ────────────────────────────────────────────────
            with TabPane("🇲🇽 MÉXICO", id="mexico"):
                with Horizontal():
                    with Vertical():
                        yield Static("── BOLSA MEXICANA (BMV / IPC) ──", classes="panel-title")
                        yield DataTable(id="mx_table", show_cursor=True, zebra_stripes=True)
                    with Vertical(id="mx_detail"):
                        yield Static("── DETALLE MX ──", classes="panel-title")
                        yield Static("Selecciona un ticker", id="mx_detail_content")

            # ── Tab 4: Global ────────────────────────────────────────────────
            with TabPane("🌏 GLOBAL", id="global"):
                yield Static("── MERCADOS INTERNACIONALES ──", classes="panel-title")
                with Horizontal():
                    with Vertical():
                        yield Static("Nikkei / Asia / Europa", classes="section-label")
                        yield DataTable(id="global_table", show_cursor=False, zebra_stripes=True)
                    with Vertical():
                        yield Static("── OIL & ENERGÍA ──", classes="section-label")
                        yield DataTable(id="oil_table", show_cursor=False, zebra_stripes=True)
                        yield Static("── CORRELACIONES ──", classes="section-label")
                        yield Static("", id="corr_panel")

            # ── Tab 5: Análisis Técnico ───────────────────────────────────────
            with TabPane("📈 ANÁLISIS", id="analisis"):
                with Vertical():
                    with Horizontal():
                        yield Input(placeholder="Ticker para analizar...", id="ta_ticker_input")
                        yield Select(
                            [("3 meses", "3mo"), ("6 meses", "6mo"), ("1 año", "1y"), ("2 años", "2y")],
                            value="3mo",
                            id="ta_period_select",
                        )
                        yield Button("Analizar", id="ta_analyze_btn", variant="primary")
                    yield Static("── GRÁFICA (ASCII) ──", classes="panel-title")
                    yield Static("", id="chart_panel")
                    yield Static("── INDICADORES TÉCNICOS ──", classes="panel-title")
                    yield Static("", id="indicators_panel")
                    yield Static("── SEÑALES ──", classes="panel-title")
                    yield Static("", id="signals_panel")

            # ── Tab 6: Predicción Estadística ────────────────────────────────
            with TabPane("🔮 PREDICCIÓN", id="prediccion"):
                with Vertical():
                    with Horizontal():
                        yield Input(placeholder="Ticker para predicción...", id="pred_ticker_input")
                        yield Button("Predecir", id="pred_btn", variant="primary")
                    yield Static("── ANÁLISIS ESTADÍSTICO PROFESIONAL ──", classes="panel-title")
                    with ScrollableContainer():
                        yield Static("", id="prediction_panel")

            # ── Tab 7: CETES & Banxico ────────────────────────────────────────
            with TabPane("🏦 CETES", id="cetes"):
                with Vertical():
                    yield Static("── CETES DIRECTO (Banco de México) ──", classes="panel-title")
                    yield DataTable(id="cetes_table", show_cursor=False, zebra_stripes=True)
                    yield Static("── INDICADORES BANXICO ──", classes="panel-title")
                    yield DataTable(id="banxico_table", show_cursor=False, zebra_stripes=True)
                    yield Static("── CONFIGURAR TOKEN BANXICO ──", classes="panel-title")
                    with Horizontal():
                        yield Input(
                            value=self.config.get("banxico_token", ""),
                            placeholder="Token gratuito: banxico.org.mx/SieAPIRest",
                            id="banxico_token_input",
                            password=False,
                        )
                        yield Button("Guardar Token", id="save_token_btn")
                    yield Static(
                        "  [dim]Obtén tu token gratis en: https://www.banxico.org.mx/SieAPIRest/service/v1/token[/dim]",
                        markup=True
                    )

            # ── Tab 8: Noticias ──────────────────────────────────────────────
            with TabPane("📰 NOTICIAS", id="noticias"):
                yield Static("── NOTICIAS EN TIEMPO REAL ──", classes="panel-title")
                with ScrollableContainer(id="news_scroll"):
                    yield Static("Cargando noticias...", id="news_content")

            # ── Tab 9: Algoritmo ──────────────────────────────────────────────
            with TabPane("🤖 ALGORITMO", id="algoritmo"):
                with Horizontal():
                    with Vertical():
                        yield Static("── MIS ALGORITMOS ──", classes="panel-title")
                        yield DataTable(id="algo_table", show_cursor=True, zebra_stripes=True)
                        yield Static("── TICKER PARA EVALUAR ──", classes="panel-title")
                        with Horizontal():
                            yield Input(placeholder="Ticker...", id="algo_ticker_input")
                            yield Button("Evaluar", id="algo_eval_btn", variant="primary")
                            yield Button("Backtest", id="algo_bt_btn", variant="default")
                    with Vertical():
                        yield Static("── RESULTADO ──", classes="panel-title")
                        with ScrollableContainer(id="algo_rules"):
                            yield Static("", id="algo_result_panel")
                        yield Static("── EDITAR REGLAS (JSON) ──", classes="panel-title")
                        yield TextArea("", id="algo_editor", language="json")
                        with Horizontal():
                            yield Button("💾 Guardar", id="algo_save_btn")
                            yield Button("📋 Cargar Sel.", id="algo_load_btn")

        yield Footer()

    # ─── Inicialización ───────────────────────────────────────────────────────
    def on_mount(self) -> None:
        self._setup_tables()
        self._start_background_refresh()
        self.set_interval(2, self._update_clock)
        self.set_interval(self.config.get("refresh_interval", 45), self._bg_refresh_trigger)

    def _setup_tables(self):
        """Configura columnas de todas las tablas."""
        # Índices
        t = self.query_one("#idx_table", DataTable)
        t.add_columns("Índice", "Precio", "Cambio%", "")

        # Crypto
        t = self.query_one("#crypto_table", DataTable)
        t.add_columns("Crypto", "Precio USD", "Cambio%", "MCap")

        # Commodities
        t = self.query_one("#comm_table", DataTable)
        t.add_columns("Activo", "Precio", "Cambio%", "Tipo")

        # US stocks
        t = self.query_one("#us_table", DataTable)
        t.add_columns("Ticker", "Nombre", "Precio", "Cambio%", "Volumen", "M.Cap")

        # MX stocks
        t = self.query_one("#mx_table", DataTable)
        t.add_columns("Ticker", "Nombre", "Precio", "Cambio%", "Volumen", "M.Cap")

        # Global
        t = self.query_one("#global_table", DataTable)
        t.add_columns("Índice", "País", "Precio", "Cambio%")

        # Oil
        t = self.query_one("#oil_table", DataTable)
        t.add_columns("Producto", "Precio", "Cambio%", "Unidad")

        # CETES dashboard
        t = self.query_one("#cetes_dash_table", DataTable)
        t.add_columns("Instrumento", "Tasa Anual", "Tasa Mensual")

        # CETES full
        t = self.query_one("#cetes_table", DataTable)
        t.add_columns("Plazo", "Tasa Anual", "Tasa Mensual", "Equiv. Diaria", "Fecha")

        # Banxico
        t = self.query_one("#banxico_table", DataTable)
        t.add_columns("Indicador", "Valor", "Fecha")

        # Algorithms
        t = self.query_one("#algo_table", DataTable)
        t.add_columns("Algoritmo", "Lógica", "# Reglas", "Activo")

        self._populate_algo_table()

    def _populate_algo_table(self):
        t = self.query_one("#algo_table", DataTable)
        t.clear()
        for algo in load_algorithms():
            t.add_row(
                algo.get("name", ""),
                algo.get("logic", "ANY"),
                str(len(algo.get("rules", []))),
                "✓" if algo.get("enabled", True) else "✗",
                key=algo.get("name"),
            )

    # ─── Refresco de datos ────────────────────────────────────────────────────
    def _start_background_refresh(self):
        t = threading.Thread(target=self._fetch_all_data, daemon=True)
        t.start()

    def _bg_refresh_trigger(self):
        t = threading.Thread(target=self._fetch_all_data, daemon=True)
        t.start()

    def _fetch_all_data(self):
        """Descarga todos los datos en background."""
        config = self.config

        # Índices
        idx_symbols = list(INDICES.keys())
        q_idx = get_quotes_bulk(idx_symbols)
        with self._data_lock:
            self._quotes_idx = q_idx

        # US Stocks
        us_syms = config.get("watchlist_us", []) + config.get("custom_tickers", [])
        q_us = get_quotes_bulk(us_syms)
        with self._data_lock:
            self._quotes_us = q_us

        # MX Stocks
        mx_syms = config.get("watchlist_mx", [])
        q_mx = get_quotes_bulk(mx_syms)
        with self._data_lock:
            self._quotes_mx = q_mx

        # Crypto
        q_crypto = get_quotes_bulk(list(CRYPTO.keys()))
        with self._data_lock:
            self._quotes_crypto = q_crypto

        # Commodities + Forex
        comm_keys = list(COMMODITIES.keys()) + list(FOREX.keys())
        q_comm = get_quotes_bulk(comm_keys)
        with self._data_lock:
            self._quotes_comm = q_comm

        # Banxico / CETES
        token = config.get("banxico_token", "")
        if token:
            banxico = get_all_banxico_data(token)
            cetes = get_cetes_summary(token)
        else:
            banxico = {}
            # Fallback CETES desde yfinance (aproximado)
            cetes = _cetes_fallback()

        with self._data_lock:
            self._banxico_data = banxico
            self._cetes_data = cetes

        # Noticias
        news = get_latest_news(40)
        with self._data_lock:
            self._news_data = news

        # Actualizar UI en el hilo principal
        self.call_from_thread(self._update_all_ui)

    def _update_all_ui(self):
        """Actualiza todos los paneles con datos frescos."""
        self.last_update = datetime.now().strftime("%H:%M:%S")
        self._update_clock()
        self._update_indices_table()
        self._update_crypto_table()
        self._update_commodities_table()
        self._update_us_table()
        self._update_mx_table()
        self._update_global_table()
        self._update_cetes_panels()
        self._update_news_panel()
        self._update_market_status()

    def _update_clock(self):
        now_ct = datetime.now(pytz.timezone("America/Mexico_City"))
        now_et = datetime.now(pytz.timezone("America/New_York"))
        is_open_us, status_us = is_market_open("US")
        is_open_mx, status_mx = is_market_open("MX")
        self.market_status_us = status_us
        self.market_status_mx = status_mx
        # Update header subtitle via title
        us_color = "green" if is_open_us else "red"
        mx_color = "green" if is_open_mx else "red"
        self.sub_title = (
            f"NYSE:[{us_color}]{status_us}[/] | BMV:[{mx_color}]{status_mx}[/] | "
            f"CT:{now_ct.strftime('%H:%M')} | ET:{now_et.strftime('%H:%M')} | "
            f"Actualizado:{self.last_update}"
        )

    # ─── Actualizaciones de tablas ────────────────────────────────────────────
    def _update_indices_table(self):
        t = self.query_one("#idx_table", DataTable)
        t.clear()
        with self._data_lock:
            quotes = self._quotes_idx.copy()
        for sym, name in INDICES.items():
            q = quotes.get(sym, {})
            price = q.get("price", 0)
            pct = q.get("change_pct", 0)
            color = price_color(pct)
            arrow = "▲" if pct > 0 else ("▼" if pct < 0 else "◆")
            t.add_row(
                Text(name, style=f"{WHITE}"),
                Text(fmt_price(price), style=f"bold {color}"),
                Text(f"{arrow}{abs(pct):.2f}%", style=color),
                Text("●", style="green" if pct > 0 else "red"),
            )

    def _update_crypto_table(self):
        t = self.query_one("#crypto_table", DataTable)
        t.clear()
        with self._data_lock:
            quotes = self._quotes_crypto.copy()
        for sym, name in CRYPTO.items():
            q = quotes.get(sym, {})
            price = q.get("price", 0)
            pct = q.get("change_pct", 0)
            mcap = q.get("market_cap", 0)
            color = price_color(pct)
            arrow = "▲" if pct > 0 else ("▼" if pct < 0 else "◆")
            t.add_row(
                Text(name, style=ORANGE),
                Text(f"${price:,.2f}", style=f"bold {color}"),
                Text(f"{arrow}{abs(pct):.2f}%", style=color),
                Text(fmt_market_cap(mcap), style=CYAN),
            )

    def _update_commodities_table(self):
        t = self.query_one("#comm_table", DataTable)
        t.clear()
        with self._data_lock:
            quotes = self._quotes_comm.copy()

        comm_display = {
            "GC=F":  ("Oro",           "Metales",    "USD/oz"),
            "SI=F":  ("Plata",         "Metales",    "USD/oz"),
            "CL=F":  ("WTI Crude",     "Energía",    "USD/bbl"),
            "BZ=F":  ("Brent Crude",   "Energía",    "USD/bbl"),
            "NG=F":  ("Gas Natural",   "Energía",    "USD/mmBtu"),
            "HG=F":  ("Cobre",         "Metales",    "USD/lb"),
            "MXN=X": ("USD/MXN",       "Forex",      "MXN"),
            "EURUSD=X": ("EUR/USD",    "Forex",      "USD"),
            "GBPUSD=X": ("GBP/USD",    "Forex",      "USD"),
        }
        for sym, (name, cat, unit) in comm_display.items():
            q = quotes.get(sym, {})
            price = q.get("price", 0)
            pct = q.get("change_pct", 0)
            color = price_color(pct)
            arrow = "▲" if pct > 0 else ("▼" if pct < 0 else "◆")
            decimals = 4 if "=X" in sym else 2
            t.add_row(
                Text(name, style=YELLOW),
                Text(fmt_price(price, decimals), style=f"bold {color}"),
                Text(f"{arrow}{abs(pct):.2f}%", style=color),
                Text(cat, style=GRAY),
            )

    def _update_us_table(self):
        t = self.query_one("#us_table", DataTable)
        t.clear()
        with self._data_lock:
            quotes = self._quotes_us.copy()
        for sym in self.config.get("watchlist_us", []) + self.config.get("custom_tickers", []):
            q = quotes.get(sym, {})
            if not q:
                continue
            price = q.get("price", 0)
            pct = q.get("change_pct", 0)
            vol = q.get("volume", 0)
            mcap = q.get("market_cap", 0)
            color = price_color(pct)
            arrow = "▲" if pct > 0 else ("▼" if pct < 0 else "◆")
            t.add_row(
                Text(sym, style=f"bold {ORANGE}"),
                Text(sym, style=WHITE),  # nombre simplificado
                Text(f"${price:,.2f}", style=f"bold {color}"),
                Text(f"{arrow}{abs(pct):.2f}%", style=color),
                Text(fmt_volume(vol), style=GRAY),
                Text(fmt_market_cap(mcap), style=CYAN),
                key=sym,
            )

    def _update_mx_table(self):
        t = self.query_one("#mx_table", DataTable)
        t.clear()
        with self._data_lock:
            quotes = self._quotes_mx.copy()
        for sym in self.config.get("watchlist_mx", []):
            q = quotes.get(sym, {})
            if not q:
                continue
            price = q.get("price", 0)
            pct = q.get("change_pct", 0)
            vol = q.get("volume", 0)
            mcap = q.get("market_cap", 0)
            color = price_color(pct)
            arrow = "▲" if pct > 0 else ("▼" if pct < 0 else "◆")
            short = sym.replace(".MX", "")
            t.add_row(
                Text(short, style=f"bold {ORANGE}"),
                Text(short, style=WHITE),
                Text(f"${price:,.2f}", style=f"bold {color}"),
                Text(f"{arrow}{abs(pct):.2f}%", style=color),
                Text(fmt_volume(vol), style=GRAY),
                Text(fmt_market_cap(mcap), style=CYAN),
                key=sym,
            )

    def _update_global_table(self):
        gt = self.query_one("#global_table", DataTable)
        gt.clear()
        ot = self.query_one("#oil_table", DataTable)
        ot.clear()
        with self._data_lock:
            quotes = self._quotes_idx.copy()
            comm = self._quotes_comm.copy()

        global_display = {
            "^N225":    ("Nikkei 225",  "Japón"),
            "000001.SS":("Shanghai",    "China"),
            "^HSI":     ("Hang Seng",   "HK/China"),
            "^FTSE":    ("FTSE 100",    "UK"),
            "^GDAXI":   ("DAX",         "Alemania"),
        }
        for sym, (name, country) in global_display.items():
            q = quotes.get(sym, {})
            price = q.get("price", 0)
            pct = q.get("change_pct", 0)
            color = price_color(pct)
            arrow = "▲" if pct > 0 else "▼" if pct < 0 else "◆"
            gt.add_row(
                Text(name, style=WHITE),
                Text(country, style=GRAY),
                Text(fmt_price(price), style=f"bold {color}"),
                Text(f"{arrow}{abs(pct):.2f}%", style=color),
            )

        oil_display = [("GC=F", "Oro",       "USD/oz"),
                       ("SI=F", "Plata",      "USD/oz"),
                       ("CL=F", "WTI Oil",    "USD/bbl"),
                       ("BZ=F", "Brent Oil",  "USD/bbl"),
                       ("NG=F", "Gas Natural","USD/mmBtu"),
                       ("HG=F", "Cobre",      "USD/lb")]
        for sym, name, unit in oil_display:
            q = comm.get(sym, {})
            price = q.get("price", 0)
            pct = q.get("change_pct", 0)
            color = price_color(pct)
            arrow = "▲" if pct > 0 else "▼" if pct < 0 else "◆"
            ot.add_row(
                Text(name, style=YELLOW),
                Text(f"${price:,.2f}", style=f"bold {color}"),
                Text(f"{arrow}{abs(pct):.2f}%", style=color),
                Text(unit, style=GRAY),
            )

    def _update_cetes_panels(self):
        with self._data_lock:
            cetes = self._cetes_data.copy()
            banxico = self._banxico_data.copy()

        # Dashboard mini
        dt = self.query_one("#cetes_dash_table", DataTable)
        dt.clear()
        for c in cetes:
            tasa = f"{c['tasa_anual']:.2f}%" if c['tasa_anual'] else "N/A"
            mens = f"{c['tasa_mensual']:.3f}%" if c['tasa_mensual'] else "N/A"
            dt.add_row(
                Text(f"CETES {c['plazo']}", style=ORANGE),
                Text(tasa, style=GREEN),
                Text(mens, style=CYAN),
            )

        # CETES full tab
        ct = self.query_one("#cetes_table", DataTable)
        ct.clear()
        for c in cetes:
            tasa = c.get("tasa_anual")
            tasa_str = f"{tasa:.4f}%" if tasa else "N/A"
            mens_str = f"{c['tasa_mensual']:.4f}%" if c.get("tasa_mensual") else "N/A"
            diaria = f"{tasa/365:.5f}%" if tasa else "N/A"
            ct.add_row(
                Text(f"CETES {c['plazo']}", style=f"bold {ORANGE}"),
                Text(tasa_str, style=f"bold {GREEN}"),
                Text(mens_str, style=CYAN),
                Text(diaria, style=WHITE),
                Text(c.get("fecha", "N/A"), style=GRAY),
            )

        # Banxico indicators
        bt = self.query_one("#banxico_table", DataTable)
        bt.clear()
        for name, data in banxico.items():
            val = data.get("value")
            val_str = f"{val:.4f}" if isinstance(val, float) else "N/A"
            if "tasa" in name.lower() or "CETES" in name or "TIIE" in name:
                val_str += "%" if val else ""
            bt.add_row(
                Text(name, style=WHITE),
                Text(val_str, style=f"bold {YELLOW}"),
                Text(data.get("date", "N/A"), style=GRAY),
            )

    def _update_news_panel(self):
        with self._data_lock:
            news = self._news_data.copy()

        lines = []
        for item in news[:40]:
            age = fmt_news_age(item["date"])
            source = item.get("source", "")[:25]
            title = item.get("title", "")[:90]
            lines.append(f"[{GRAY}]{age}[/] [{CYAN}]{source}[/]")
            lines.append(f"  [{WHITE}]{title}[/]")
            lines.append("")

        content = "\n".join(lines) if lines else "Sin noticias disponibles"

        try:
            self.query_one("#news_content", Static).update(content)
            self.query_one("#dash_news_content", Static).update(
                "\n".join(lines[:30]) if lines else "Sin noticias"
            )
        except Exception:
            pass

    def _update_market_status(self):
        is_open_us, status_us = is_market_open("US")
        is_open_mx, status_mx = is_market_open("MX")

        now_ct = datetime.now(pytz.timezone("America/Mexico_City"))
        now_et = datetime.now(pytz.timezone("America/New_York"))
        now_jp = datetime.now(pytz.timezone("Asia/Tokyo"))

        us_col = GREEN if is_open_us else RED
        mx_col = GREEN if is_open_mx else RED

        content = (
            f"[{us_col}]● NYSE/NASDAQ: {status_us}[/]\n"
            f"[{mx_col}]● BMV México: {status_mx}[/]\n"
            f"\n"
            f"[{GRAY}]Hora México (CT): {now_ct.strftime('%H:%M:%S')}[/]\n"
            f"[{GRAY}]Hora NY (ET):     {now_et.strftime('%H:%M:%S')}[/]\n"
            f"[{GRAY}]Hora Tokio:       {now_jp.strftime('%H:%M:%S')}[/]\n"
        )
        try:
            self.query_one("#market_status_panel", Static).update(content)
        except Exception:
            pass

    # ─── Eventos de usuario ───────────────────────────────────────────────────
    def on_button_pressed(self, event: Button.Pressed) -> None:
        btn_id = event.button.id

        if btn_id == "search_btn":
            self._handle_search()
        elif btn_id == "ta_analyze_btn":
            self._handle_ta_analysis()
        elif btn_id == "pred_btn":
            self._handle_prediction()
        elif btn_id == "save_token_btn":
            self._handle_save_token()
        elif btn_id == "algo_eval_btn":
            self._handle_algo_eval()
        elif btn_id == "algo_bt_btn":
            self._handle_algo_backtest()
        elif btn_id == "algo_save_btn":
            self._handle_algo_save()
        elif btn_id == "algo_load_btn":
            self._handle_algo_load()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "ticker_input":
            self._handle_search()
        elif event.input.id == "ta_ticker_input":
            self._handle_ta_analysis()
        elif event.input.id == "pred_ticker_input":
            self._handle_prediction()
        elif event.input.id == "algo_ticker_input":
            self._handle_algo_eval()

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        table_id = event.data_table.id
        if event.row_key is None:
            return
        sym = str(event.row_key.value)
        if table_id in ("us_table", "mx_table"):
            self.selected_symbol = sym
            self._show_detail(sym, table_id)
        elif table_id == "algo_table":
            self._load_algo_to_editor(sym)

    def _handle_search(self):
        try:
            ticker = self.query_one("#ticker_input", Input).value.strip().upper()
            if not ticker:
                return
            # Agregar a watchlist custom si no está
            custom = self.config.get("custom_tickers", [])
            us_list = self.config.get("watchlist_us", [])
            mx_list = self.config.get("watchlist_mx", [])
            if ticker not in us_list and ticker not in mx_list and ticker not in custom:
                custom.append(ticker)
                self.config["custom_tickers"] = custom
                save_config(self.config)
            self.selected_symbol = ticker
            self._show_detail(ticker, "us_table")
        except Exception:
            pass

    @work(thread=True)
    def _show_detail(self, symbol: str, table_id: str):
        """Muestra detalle de un ticker en el panel derecho."""
        q = get_quote(symbol)
        info = get_company_info(symbol)
        df = get_history(symbol, period="3mo", interval="1d")

        with self._data_lock:
            self._selected_df = df
            self._company_info = info

        ta_sum = analyze(df, symbol) if not df.empty else None
        algo_res = evaluate_all_algorithms(ta_sum, q.get("price", 0), df) if ta_sum else []
        consensus, conf = aggregate_algo_signals(algo_res) if algo_res else ("N/A", 0)

        content = self._build_detail_content(q, info, ta_sum, algo_res, consensus, conf)

        panel_id = "mx_detail_content" if table_id == "mx_table" else "detail_content"
        self.call_from_thread(
            lambda: self.query_one(f"#{panel_id}", Static).update(content)
        )

    def _build_detail_content(self, q, info, ta, algo_res, consensus, conf) -> str:
        sym = q.get("symbol", "")
        price = q.get("price", 0)
        pct = q.get("change_pct", 0)
        color = GREEN if pct > 0 else RED
        arrow = "▲" if pct > 0 else "▼"

        lines = [
            f"[bold {ORANGE}]{info.get('name', sym)}[/]",
            f"[{GRAY}]{info.get('sector','N/A')} | {info.get('industry','N/A')} | {info.get('country','N/A')}[/]",
            "─" * 40,
            f"[bold {color}]{arrow} ${price:,.4f}  ({pct:+.2f}%)[/]",
            f"[{GRAY}]Abierto: ${q.get('open',0):,.2f}  "
            f"Máx: ${q.get('high',0):,.2f}  Mín: ${q.get('low',0):,.2f}[/]",
            f"[{GRAY}]Cierre ant.: ${q.get('prev_close',0):,.2f}[/]",
            f"[{CYAN}]Volumen: {fmt_volume(q.get('volume',0))}  "
            f"M.Cap: {fmt_market_cap(q.get('market_cap',0))}[/]",
        ]

        # Pre/Post market
        pre = q.get("pre_market")
        post = q.get("post_market")
        if pre:
            pre_ch = (pre - price) / price * 100 if price else 0
            pre_col = GREEN if pre_ch > 0 else RED
            lines.append(f"[{pre_col}]PRE-MARKET: ${pre:,.2f} ({pre_ch:+.2f}%)[/]")
        if post:
            post_ch = (post - price) / price * 100 if price else 0
            post_col = GREEN if post_ch > 0 else RED
            lines.append(f"[{post_col}]POST-MARKET: ${post:,.2f} ({post_ch:+.2f}%)[/]")

        lines.append("─" * 40)

        # Fundamentales
        pe = info.get("pe_ratio")
        beta = info.get("beta")
        div = info.get("dividend_yield")
        h52 = info.get("52w_high")
        l52 = info.get("52w_low")
        lines.append(f"[{WHITE}]P/E: {pe:.1f}  Beta: {beta:.2f}  Div.Yld: {div:.2%}[/]"
                     if all(x is not None for x in [pe, beta, div]) else
                     f"[{GRAY}]P/E: {pe or 'N/A'}  Beta: {beta or 'N/A'}[/]")
        if h52 and l52:
            pct_from_high = (price - h52) / h52 * 100 if h52 else 0
            lines.append(f"[{GRAY}]52sem Máx: ${h52:,.2f}  52sem Mín: ${l52:,.2f}[/]")
            lines.append(f"[{GRAY}]Desde máx 52sem: {pct_from_high:.1f}%[/]")

        # Indicadores técnicos resumen
        if ta:
            lines.append("─" * 40)
            lines.append(f"[{ORANGE}]── TÉCNICO ──[/]")
            rsi_col = GREEN if ta.rsi and ta.rsi < 30 else (RED if ta.rsi and ta.rsi > 70 else WHITE)
            lines.append(f"RSI: [{rsi_col}]{ta.rsi:.1f}[/]  "
                         f"MACD: [{WHITE}]{ta.macd:.3f}[/]"
                         if ta.rsi and ta.macd else "RSI: N/A  MACD: N/A")

            if ta.bb_pct is not None:
                bb_col = GREEN if ta.bb_pct < 0.2 else (RED if ta.bb_pct > 0.8 else WHITE)
                lines.append(f"BB%: [{bb_col}]{ta.bb_pct:.1%}[/]  ADX: {ta.adx:.1f}"
                              if ta.adx else f"BB%: [{bb_col}]{ta.bb_pct:.1%}[/]")

            sig_col = signal_color(ta.overall_signal)
            lines.append(f"Señal Técnica: [bold {sig_col}]{signal_emoji(ta.overall_signal)}[/]")
            lines.append(f"BUY:{ta.buy_score} SELL:{ta.sell_score} NEUTRAL:{ta.neutral_score}")

        # Algoritmos
        if algo_res:
            lines.append("─" * 40)
            lines.append(f"[{ORANGE}]── MIS ALGORITMOS ──[/]")
            for r in algo_res:
                col = signal_color(r.signal)
                lines.append(f"[{GRAY}]{r.algorithm_name[:20]}[/]: [bold {col}]{r.signal}[/] ({r.confidence:.0%})")
            cons_col = signal_color(consensus)
            lines.append(f"[bold]CONSENSO: [{cons_col}]{consensus}[/] [{conf:.0%}][/]")

        return "\n".join(lines)

    @work(thread=True)
    def _handle_ta_analysis(self):
        try:
            ticker = self.query_one("#ta_ticker_input", Input).value.strip().upper()
            period = self.query_one("#ta_period_select", Select).value
            if not ticker:
                return

            df = get_history(ticker, period=str(period), interval="1d")
            if df.empty:
                self.call_from_thread(
                    lambda: self.query_one("#chart_panel", Static).update(f"No hay datos para {ticker}")
                )
                return

            # Gráfica ASCII
            chart = _build_ascii_chart(df, ticker)
            # Indicadores
            ta = analyze(df, ticker)
            indicators = _build_indicators_text(ta)
            signals = _build_signals_text(ta)

            self.call_from_thread(lambda: self.query_one("#chart_panel", Static).update(chart))
            self.call_from_thread(lambda: self.query_one("#indicators_panel", Static).update(indicators))
            self.call_from_thread(lambda: self.query_one("#signals_panel", Static).update(signals))
        except Exception as e:
            self.call_from_thread(
                lambda: self.query_one("#chart_panel", Static).update(f"Error: {e}")
            )

    @work(thread=True)
    def _handle_prediction(self):
        try:
            ticker = self.query_one("#pred_ticker_input", Input).value.strip().upper()
            if not ticker:
                return

            df = get_history(ticker, period="1y", interval="1d")
            if df.empty:
                self.call_from_thread(
                    lambda: self.query_one("#prediction_panel", Static).update(f"No hay datos para {ticker}")
                )
                return

            result = full_analysis(df, ticker)
            content = _build_prediction_text(result)

            self.call_from_thread(
                lambda: self.query_one("#prediction_panel", Static).update(content)
            )
        except Exception as e:
            self.call_from_thread(
                lambda: self.query_one("#prediction_panel", Static).update(f"Error: {e}")
            )

    def _handle_save_token(self):
        try:
            token = self.query_one("#banxico_token_input", Input).value.strip()
            self.config["banxico_token"] = token
            save_config(self.config)
            self.notify("Token de Banxico guardado.", title="✓ Guardado")
            # Refrescar datos Banxico
            t = threading.Thread(target=self._fetch_all_data, daemon=True)
            t.start()
        except Exception as e:
            self.notify(f"Error: {e}", severity="error")

    @work(thread=True)
    def _handle_algo_eval(self):
        try:
            ticker = self.query_one("#algo_ticker_input", Input).value.strip().upper()
            if not ticker:
                return

            df = get_history(ticker, period="3mo", interval="1d")
            q = get_quote(ticker)
            price = q.get("price", 0)
            ta = analyze(df, ticker) if not df.empty else None

            if not ta:
                self.call_from_thread(
                    lambda: self.query_one("#algo_result_panel", Static).update("No hay datos")
                )
                return

            results = evaluate_all_algorithms(ta, price, df)
            consensus, conf = aggregate_algo_signals(results)
            content = _build_algo_result_text(ticker, price, results, consensus, conf)

            self.call_from_thread(
                lambda: self.query_one("#algo_result_panel", Static).update(content)
            )
        except Exception as e:
            self.call_from_thread(
                lambda: self.query_one("#algo_result_panel", Static).update(f"Error: {e}")
            )

    @work(thread=True)
    def _handle_algo_backtest(self):
        try:
            ticker = self.query_one("#algo_ticker_input", Input).value.strip().upper()
            if not ticker:
                return

            df = get_history(ticker, period="1y", interval="1d")
            algos = load_algorithms()
            enabled = [a for a in algos if a.get("enabled", True)]
            if not enabled:
                return

            results_text = [f"[bold {ORANGE}]BACKTEST: {ticker} (1 año)[/]\n"]
            for algo in enabled[:4]:  # máximo 4 para no tardar
                bt = backtest_algorithm(algo, df, ticker)
                results_text.append(_build_backtest_text(bt))

            content = "\n".join(results_text)
            self.call_from_thread(
                lambda: self.query_one("#algo_result_panel", Static).update(content)
            )
        except Exception as e:
            self.call_from_thread(
                lambda: self.query_one("#algo_result_panel", Static).update(f"Error backtest: {e}")
            )

    def _handle_algo_save(self):
        import json
        try:
            text = self.query_one("#algo_editor", TextArea).text.strip()
            if not text:
                return
            data = json.loads(text)
            if isinstance(data, dict):
                data = [data]
            algos = load_algorithms()
            # Actualizar o agregar
            for new_algo in data:
                name = new_algo.get("name", "")
                found = False
                for i, a in enumerate(algos):
                    if a.get("name") == name:
                        algos[i] = new_algo
                        found = True
                        break
                if not found:
                    algos.append(new_algo)
            save_algorithms(algos)
            self._populate_algo_table()
            self.notify("Algoritmo guardado.", title="✓ Guardado")
        except Exception as e:
            self.notify(f"JSON inválido: {e}", severity="error")

    def _handle_algo_load(self):
        import json
        try:
            t = self.query_one("#algo_table", DataTable)
            if t.cursor_row is None:
                return
            row_key = t.get_row_at(t.cursor_row)
            name = str(row_key[0])
            algos = load_algorithms()
            for a in algos:
                if a.get("name") == name:
                    self.query_one("#algo_editor", TextArea).load_text(
                        json.dumps(a, indent=2, ensure_ascii=False)
                    )
                    break
        except Exception:
            pass

    def _load_algo_to_editor(self, name: str):
        import json
        try:
            algos = load_algorithms()
            for a in algos:
                if a.get("name") == name:
                    self.query_one("#algo_editor", TextArea).load_text(
                        json.dumps(a, indent=2, ensure_ascii=False)
                    )
                    break
        except Exception:
            pass

    def action_refresh_all(self):
        self.notify("Actualizando datos...", title="Refrescando")
        t = threading.Thread(target=self._fetch_all_data, daemon=True)
        t.start()

    def action_switch_tab(self, tab_id: str):
        try:
            self.query_one("#tabs", TabbedContent).active = tab_id
        except Exception:
            pass


# ─── Helpers de renderizado ────────────────────────────────────────────────────
def _build_ascii_chart(df: pd.DataFrame, symbol: str, width: int = 80, height: int = 18) -> str:
    """Genera un gráfico de velas ASCII simple."""
    try:
        close = df["Close"].astype(float).squeeze().tail(width)
        prices = close.values
        n = len(prices)
        if n < 2:
            return "Datos insuficientes"

        min_p = min(prices)
        max_p = max(prices)
        price_range = max_p - min_p or 1

        chart_lines = []
        for row in range(height - 1, -1, -1):
            threshold = min_p + (row / (height - 1)) * price_range
            line = ""
            for i, p in enumerate(prices):
                if i > 0:
                    prev = prices[i - 1]
                    if (p >= threshold >= prev) or (p <= threshold <= prev):
                        line += "│" if abs(p - threshold) < price_range / height else "╌"
                    elif p >= threshold:
                        ch = p.item() if hasattr(p, 'item') else float(p)
                        prev_ch = prev.item() if hasattr(prev, 'item') else float(prev)
                        color_char = "▀" if ch > prev_ch else "▄"
                        line += color_char
                    else:
                        line += " "
                else:
                    line += "▀" if p >= threshold else " "

            price_label = f" {threshold:>8.2f}"
            chart_lines.append(price_label + "│" + line)

        # Eje X
        chart_lines.append(" " * 10 + "└" + "─" * n)
        dates = df.index[-n:]
        start_d = str(dates[0])[:10]
        end_d = str(dates[-1])[:10]
        chart_lines.append(f" " * 11 + f"{start_d}" + " " * max(0, n - 20 - len(start_d)) + f"{end_d}")

        header = f"[bold {ORANGE}]{symbol}[/]  {prices[-1]:,.2f}  "
        ch = prices[-1] - prices[-2] if len(prices) >= 2 else 0
        color = GREEN if ch >= 0 else RED
        header += f"[{color}]{ch:+.2f} ({ch/prices[-2]*100:+.2f}%)[/]"

        return header + "\n" + "\n".join(chart_lines)
    except Exception as e:
        return f"Error al generar gráfica: {e}"


def _build_indicators_text(ta) -> str:
    lines = [
        f"[bold {ORANGE}]RSI(14):[/]   {_fmt_indicator(ta.rsi, '.1f')}   "
        f"[bold {ORANGE}]MACD:[/]   {_fmt_indicator(ta.macd, '.4f')}   "
        f"[bold {ORANGE}]MACD Hist:[/]   {_fmt_indicator(ta.macd_hist, '.4f')}",

        f"[bold {ORANGE}]BB Superior:[/]  {_fmt_indicator(ta.bb_upper, '.2f')}   "
        f"[bold {ORANGE}]BB Medio:[/]  {_fmt_indicator(ta.bb_middle, '.2f')}   "
        f"[bold {ORANGE}]BB Inferior:[/]  {_fmt_indicator(ta.bb_lower, '.2f')}",

        f"[bold {ORANGE}]EMA 20:[/]  {_fmt_indicator(ta.ema_20, '.2f')}   "
        f"[bold {ORANGE}]EMA 50:[/]  {_fmt_indicator(ta.ema_50, '.2f')}   "
        f"[bold {ORANGE}]EMA 200:[/]  {_fmt_indicator(ta.ema_200, '.2f')}",

        f"[bold {ORANGE}]SMA 20:[/]  {_fmt_indicator(ta.sma_20, '.2f')}   "
        f"[bold {ORANGE}]SMA 50:[/]  {_fmt_indicator(ta.sma_50, '.2f')}",

        f"[bold {ORANGE}]Estoc. K:[/]  {_fmt_indicator(ta.stoch_k, '.1f')}   "
        f"[bold {ORANGE}]Estoc. D:[/]  {_fmt_indicator(ta.stoch_d, '.1f')}   "
        f"[bold {ORANGE}]ADX:[/]  {_fmt_indicator(ta.adx, '.1f')}",

        f"[bold {ORANGE}]ATR:[/]  {_fmt_indicator(ta.atr, '.3f')}   "
        f"[bold {ORANGE}]CCI:[/]  {_fmt_indicator(ta.cci, '.1f')}   "
        f"[bold {ORANGE}]Williams%R:[/]  {_fmt_indicator(ta.williams_r, '.1f')}",

        f"[bold {ORANGE}]Soporte:[/]  {_fmt_indicator(ta.support, '.2f')}   "
        f"[bold {ORANGE}]Resistencia:[/]  {_fmt_indicator(ta.resistance, '.2f')}",
    ]
    return "\n".join(lines)


def _fmt_indicator(val, fmt: str) -> str:
    if val is None:
        return f"[{GRAY}]N/A[/]"
    return f"[{WHITE}]{val:{fmt.strip('{}')}}"


def _build_signals_text(ta) -> str:
    sig_col = signal_color(ta.overall_signal)
    bar = score_bar(ta.buy_score, ta.sell_score, ta.neutral_score, 24)
    lines = [
        f"[bold {sig_col}]{signal_emoji(ta.overall_signal)}[/]   "
        f"[{GREEN}]BUY:{ta.buy_score}[/] | [{YELLOW}]NEUTRAL:{ta.neutral_score}[/] | [{RED}]SELL:{ta.sell_score}[/]",
        f"[{GREEN}]{'█'*ta.buy_score}[/][{YELLOW}]{'░'*ta.neutral_score}[/][{RED}]{'▓'*ta.sell_score}[/]",
        "─" * 50,
    ]
    for sig in ta.signals:
        col = signal_color(sig.signal)
        bar_w = int(sig.strength * 10)
        strength_bar = "█" * bar_w + "░" * (10 - bar_w)
        lines.append(f"[{col}]{sig.signal:7}[/]  [{GRAY}]{strength_bar}[/]  {sig.description}")
    return "\n".join(lines)


def _build_prediction_text(r) -> str:
    trend_col = GREEN if r.trend_direction == "ALCISTA" else (RED if r.trend_direction == "BAJISTA" else YELLOW)
    sig_col = signal_color(r.stat_signal)
    conf_bar = confidence_bar(r.confidence, 15)

    lines = [
        f"[bold {ORANGE}]╔══ ANÁLISIS ESTADÍSTICO: {r.symbol} ══╗[/]",
        "",
        f"[bold {trend_col}]{trend_arrow(r.trend_direction)} TENDENCIA: {r.trend_direction}[/]",
        f"[{GRAY}]Pendiente regresión: {r.trend_slope:+.3f} pts/día   R²: {r.trend_r2:.3f}[/]",
        "",
        f"[bold {ORANGE}]── OBJETIVOS DE PRECIO (Regresión Lineal) ──[/]",
        f"  [bold]5 días:[/]  [{WHITE}]${r.trend_target_5d:,.2f}[/]   "
        f"[{GREEN if r.trend_target_5d > r.current_price else RED}]"
        f"({(r.trend_target_5d/r.current_price-1)*100:+.2f}%)[/]",
        f"  [bold]20 días:[/] [{WHITE}]${r.trend_target_20d:,.2f}[/]   "
        f"[{GREEN if r.trend_target_20d > r.current_price else RED}]"
        f"({(r.trend_target_20d/r.current_price-1)*100:+.2f}%)[/]",
        f"  [bold]60 días:[/] [{WHITE}]${r.trend_target_60d:,.2f}[/]   "
        f"[{GREEN if r.trend_target_60d > r.current_price else RED}]"
        f"({(r.trend_target_60d/r.current_price-1)*100:+.2f}%)[/]",
        "",
        f"[bold {ORANGE}]── MONTE CARLO (1000 simulaciones GBM) ──[/]",
        f"  [bold]5 días  P10/50/90:[/]  "
        f"[{RED}]${r.mc_low_5d:,.2f}[/] / [{WHITE}]${r.mc_median_5d:,.2f}[/] / [{GREEN}]${r.mc_high_5d:,.2f}[/]",
        f"  [bold]20 días P10/50/90:[/]  "
        f"[{RED}]${r.mc_low_20d:,.2f}[/] / [{WHITE}]${r.mc_median_20d:,.2f}[/] / [{GREEN}]${r.mc_high_20d:,.2f}[/]",
        "",
        f"[bold {ORANGE}]── ESTADÍSTICAS DE RIESGO ──[/]",
        f"  Volatilidad Diaria:   [{YELLOW}]{r.daily_volatility:.3%}[/]",
        f"  Volatilidad Anual:    [{YELLOW}]{r.annual_volatility:.2%}[/]",
        f"  Sharpe Ratio (aprox): [{WHITE}]{r.sharpe_proxy:.3f}[/]",
        "",
        f"[bold {ORANGE}]── PATRONES DETECTADOS ──[/]",
    ]

    for pattern in r.patterns:
        lines.append(f"  {pattern}")

    lines += [
        "",
        f"[bold {ORANGE}]── SEÑAL ESTADÍSTICA FINAL ──[/]",
        f"  [bold {sig_col}]{r.stat_signal}[/]   Confianza: [{WHITE}]{r.confidence:.1%}[/]",
        f"  [{GRAY}]{conf_bar}[/]",
        "",
        f"[{GRAY}]⚠ Nota: Análisis estadístico con fines educativos. No es asesoría financiera.[/]",
        f"[{GRAY}]  Precio actual: ${r.current_price:,.4f}[/]",
    ]
    return "\n".join(lines)


def _build_algo_result_text(ticker, price, results, consensus, conf) -> str:
    cons_col = signal_color(consensus)
    lines = [
        f"[bold {ORANGE}]╔══ EVALUACIÓN DE ALGORITMOS: {ticker} ══╗[/]",
        f"[{GRAY}]Precio actual: ${price:,.4f}[/]",
        "─" * 45,
    ]
    for r in results:
        col = signal_color(r.signal)
        lines.append(f"\n[bold {ORANGE}]{r.algorithm_name}[/]")
        lines.append(f"  Señal: [bold {col}]{r.signal}[/]   Confianza: {r.confidence:.0%}   Score: {r.score:+.2f}")
        for rule_desc in r.triggered_rules:
            lines.append(f"  [{GREEN}]✓ {rule_desc}[/]")
        if not r.triggered_rules:
            lines.append(f"  [{GRAY}]Sin reglas activadas[/]")

    lines += [
        "",
        "─" * 45,
        f"[bold]CONSENSO FINAL: [bold {cons_col}]{consensus}[/]   [{WHITE}]{conf:.0%}[/][/]",
        "",
        f"[{GRAY}]⚠ No es asesoría financiera. Usa con criterio propio.[/]",
    ]
    return "\n".join(lines)


def _build_backtest_text(bt) -> str:
    wr_col = GREEN if bt.win_rate >= 0.5 else RED
    ret_col = GREEN if bt.total_return >= 0 else RED
    sharpe_col = GREEN if bt.sharpe >= 1 else (YELLOW if bt.sharpe >= 0 else RED)

    lines = [
        f"\n[bold {ORANGE}]{bt.algorithm_name}[/]  [{GRAY}]{bt.symbol} · {bt.period}[/]",
        f"  Trades: {bt.total_trades}   "
        f"Ganadores: [{wr_col}]{bt.winning_trades}[/]   "
        f"Perdedores: [{RED}]{bt.losing_trades}[/]",
        f"  Win Rate: [{wr_col}]{bt.win_rate:.1%}[/]   "
        f"Retorno Total: [{ret_col}]{bt.total_return:+.2f}%[/]",
        f"  Max Drawdown: [{RED}]{bt.max_drawdown:.2f}%[/]   "
        f"Sharpe: [{sharpe_col}]{bt.sharpe:.2f}[/]",
    ]
    if bt.trades:
        lines.append(f"  [{GRAY}]Últimos trades:[/]")
        for t in bt.trades[-3:]:
            pnl_col = GREEN if t["pnl"] > 0 else RED
            lines.append(
                f"    [{GRAY}]{t.get('entry_date','?')} → {t.get('exit_date','?')}[/]  "
                f"[{pnl_col}]{t.get('pnl_pct', 0):+.2f}%[/]"
            )
    return "\n".join(lines)


def _cetes_fallback() -> list[dict]:
    """Datos CETES aproximados sin token Banxico (valores recientes por defecto)."""
    return [
        {"plazo": "28 días",  "days": 28,  "tasa_anual": 9.75, "tasa_mensual": 9.75/12, "fecha": "SIN TOKEN"},
        {"plazo": "91 días",  "days": 91,  "tasa_anual": 9.50, "tasa_mensual": 9.50/12, "fecha": "SIN TOKEN"},
        {"plazo": "182 días", "days": 182, "tasa_anual": 9.25, "tasa_mensual": 9.25/12, "fecha": "SIN TOKEN"},
        {"plazo": "364 días", "days": 364, "tasa_anual": 9.10, "tasa_mensual": 9.10/12, "fecha": "SIN TOKEN"},
    ]
