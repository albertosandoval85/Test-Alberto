#!/usr/bin/env python3
"""
Bloomberg Terminal Personal
───────────────────────────
Uso:
    python run_bloomberg.py

Instalar dependencias:
    pip install -r requirements_bloomberg.txt

Token Banxico (gratis, para datos CETES en tiempo real):
    https://www.banxico.org.mx/SieAPIRest/service/v1/token
    Configurar dentro del terminal en la pestaña 🏦 CETES

Atajos de teclado:
    1-9  → Cambiar pestaña
    r    → Refrescar datos
    q    → Salir
"""
import sys
import os

# Asegurar que el directorio del proyecto esté en el path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def check_dependencies():
    missing = []
    required = [
        ("textual", "textual"),
        ("yfinance", "yfinance"),
        ("pandas", "pandas"),
        ("numpy", "numpy"),
        ("scipy", "scipy"),
        ("requests", "requests"),
        ("feedparser", "feedparser"),
        ("pytz", "pytz"),
    ]
    for pkg, import_name in required:
        try:
            __import__(import_name)
        except ImportError:
            missing.append(pkg)
    return missing


def main():
    missing = check_dependencies()
    if missing:
        print("╔══════════════════════════════════════════════════╗")
        print("║  Bloomberg Terminal - Dependencias faltantes     ║")
        print("╠══════════════════════════════════════════════════╣")
        print(f"║  Ejecuta:                                         ║")
        print(f"║  pip install -r requirements_bloomberg.txt        ║")
        print("╠══════════════════════════════════════════════════╣")
        print("║  Paquetes faltantes:                              ║")
        for pkg in missing:
            print(f"║    - {pkg:<44} ║")
        print("╚══════════════════════════════════════════════════╝")
        sys.exit(1)

    print("╔══════════════════════════════════════════════════════╗")
    print("║         BLOOMBERG TERMINAL PERSONAL  v1.0            ║")
    print("║              por Alberto · Retail Investor           ║")
    print("╠══════════════════════════════════════════════════════╣")
    print("║  Iniciando terminal y descargando datos...           ║")
    print("║  Esto puede tardar 15-30 segundos en el primer uso. ║")
    print("╚══════════════════════════════════════════════════════╝")

    from bloomberg.app import BloombergApp
    app = BloombergApp()
    app.run()


if __name__ == "__main__":
    main()
