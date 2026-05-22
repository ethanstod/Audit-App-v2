# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for WH-347 Audit Engine
# Build: pyinstaller wh347_audit.spec --clean

from PyInstaller.utils.hooks import collect_all, collect_submodules

pdfminer_d,   pdfminer_b,   pdfminer_h   = collect_all("pdfminer")
pdfplumber_d, pdfplumber_b, pdfplumber_h = collect_all("pdfplumber")
webview_d,    webview_b,    webview_h    = collect_all("webview")
pandas_h   = collect_submodules("pandas")
openpyxl_h = collect_submodules("openpyxl")

a = Analysis(
    ["main.py"],
    pathex=["."],
    binaries=[] + pdfminer_b + pdfplumber_b + webview_b,
    datas=[
        ("templates",          "templates"),
        ("cleaned_rates.xlsx", "."),
        ("version.txt",        "."),
    ] + pdfminer_d + pdfplumber_d + webview_d,
    hiddenimports=[
        # Audit modules
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
        # pywebview native window (WebView2 on Windows 10/11)
        "webview",
        "webview.platforms",
        "webview.platforms.edgechromium",
        "webview.platforms.mshtml",
        # Image / data
        "PIL", "PIL.Image", "PIL.ImageDraw",
        "sqlite3", "_sqlite3",
        "openpyxl", "openpyxl.styles", "openpyxl.utils", "openpyxl.reader",
        "charset_normalizer",
        # Sentry error reporting
        "sentry_sdk", "sentry_sdk.integrations", "sentry_sdk.integrations.flask",
        "sentry_sdk.integrations.logging", "sentry_sdk.integrations.excepthook",
    ] + pdfminer_h + pdfplumber_h + webview_h + pandas_h + openpyxl_h,
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
    console=False,
    icon=None,
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
