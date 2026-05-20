# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for WH-347 Audit Engine
# Build: pyinstaller wh347_audit.spec --clean

from PyInstaller.utils.hooks import collect_all, collect_submodules

# Collect everything from packages that use dynamic imports
pdfminer_d,   pdfminer_b,   pdfminer_h   = collect_all("pdfminer")
pdfplumber_d, pdfplumber_b, pdfplumber_h = collect_all("pdfplumber")
pandas_h  = collect_submodules("pandas")
openpyxl_h = collect_submodules("openpyxl")

a = Analysis(
    ["main.py"],
    pathex=["."],
    binaries=[] + pdfminer_b + pdfplumber_b,
    datas=[
        ("templates",          "templates"),
        ("cleaned_rates.xlsx", "."),
    ] + pdfminer_d + pdfplumber_d,
    hiddenimports=[
        # Our audit modules
        "pdf_parser", "math_audit", "cwhssa_audit", "pay_audit",
        "fringe_audit", "classification_audit", "header_audit", "wh347_report",
        # Flask / Werkzeug / Jinja2
        "flask", "flask.templating", "flask.globals", "flask.sessions",
        "jinja2", "jinja2.ext", "jinja2.loaders",
        "werkzeug", "werkzeug.routing", "werkzeug.serving",
        "werkzeug.middleware.shared_data",
        "click",
        # Waitress WSGI server
        "waitress", "waitress.server", "waitress.task", "waitress.channel",
        # System tray
        "pystray", "pystray._win32",
        "PIL", "PIL.Image", "PIL.ImageDraw",
        # Data
        "sqlite3", "_sqlite3",
        "openpyxl", "openpyxl.styles", "openpyxl.utils", "openpyxl.reader",
        "charset_normalizer",
        "cryptography",
        "Crypto",
    ] + pdfminer_h + pdfplumber_h + pandas_h + openpyxl_h,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["matplotlib", "scipy", "notebook", "IPython", "tkinter"],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="WH347 Audit Engine",
    debug=False,
    strip=False,
    upx=True,
    console=False,          # No black console window
    icon=None,              # Replace with "icon.ico" if you add one
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    name="WH347 Audit Engine",
)
