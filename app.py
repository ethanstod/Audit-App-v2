import os
import sys
import sqlite3
import uuid
import threading
import subprocess
import tempfile
import json
from datetime import datetime
from urllib.request import urlopen, urlretrieve, Request as URLRequest
from urllib.error import URLError

import pandas as pd
from flask import (Flask, render_template, request, redirect,
                   url_for, send_file, jsonify, flash)

from pdf_parser import extract_wh347_data
from math_audit import audit_wh347_math
from cwhssa_audit import audit_cwhssa
from pay_audit import load_wage_table, audit_all_workers, audit_apprentice_rates, audit_deductions
from fringe_audit import audit_fringe_benefits
from classification_audit import audit_classifications
from header_audit import audit_header
from wh347_report import generate_wh347_html_report

# ---------------------------------------------------------------------------
# Path setup — works both in development and when frozen by PyInstaller
# ---------------------------------------------------------------------------

if getattr(sys, "frozen", False):
    # Running as a compiled .exe — data lives next to the exe,
    # bundled resources (templates, rates) are in sys._MEIPASS
    _DATA_DIR     = os.path.dirname(sys.executable)
    _RESOURCE_DIR = sys._MEIPASS
else:
    _DATA_DIR     = os.path.dirname(os.path.abspath(__file__))
    _RESOURCE_DIR = _DATA_DIR

# Environment variable overrides (set by main.py before importing this module)
_DATA_DIR     = os.environ.get("WH347_DATA_DIR",     _DATA_DIR)
_RESOURCE_DIR = os.environ.get("WH347_RESOURCE_DIR", _RESOURCE_DIR)

BASE_DIR   = _DATA_DIR
UPLOAD_DIR = os.path.join(_DATA_DIR, "uploads")
REPORT_DIR = os.path.join(_DATA_DIR, "reports")
DB_PATH    = os.path.join(_DATA_DIR, "audits.db")

# Prefer a rates file placed next to the exe (user-replaceable);
# fall back to the copy bundled inside the package.
_rates_beside = os.path.join(_DATA_DIR, "cleaned_rates.xlsx")
_rates_bundle = os.path.join(_RESOURCE_DIR, "cleaned_rates.xlsx")
WAGE_TABLE = _rates_beside if os.path.exists(_rates_beside) else _rates_bundle

# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------

app = Flask(__name__, template_folder=os.path.join(_RESOURCE_DIR, "templates"))
app.secret_key = os.environ.get("SECRET_KEY", "wh347-audit-dev-key")

os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(REPORT_DIR, exist_ok=True)


def _load_wage_det_info():
    try:
        df = pd.read_excel(WAGE_TABLE)
        df.columns = [c.strip().upper().replace(" ", "_") for c in df.columns]
        info = {}
        for col, key in [("WAGE_DET_NUMBER", "number"), ("CONSTRUCTION_TYPE", "type")]:
            if col in df.columns:
                vals = df[col].dropna()
                info[key] = str(vals.iloc[0]).strip() if not vals.empty else ""
            else:
                info[key] = ""
        return info
    except Exception:
        return {"number": "", "type": ""}

WAGE_DET_INFO = _load_wage_det_info()


# ---------------------------------------------------------------------------
# Auto-update
# ---------------------------------------------------------------------------

def _read_version():
    for loc in (os.path.join(_DATA_DIR, "version.txt"),
                os.path.join(_RESOURCE_DIR, "version.txt")):
        try:
            with open(loc) as f:
                return f.read().strip()
        except Exception:
            continue
    return "0.0.0"

APP_VERSION = _read_version()

_update_info = {"version": None, "url": None}


def _ver_tuple(v):
    try:
        return tuple(int(x) for x in v.lstrip("v").split("."))
    except Exception:
        return (0, 0, 0)


def _check_for_update():
    try:
        req = URLRequest(
            "https://api.github.com/repos/ethanstod/Audit-App-v2/releases/latest",
            headers={"User-Agent": "WH347AuditEngine",
                     "Accept": "application/vnd.github+json"}
        )
        data = json.loads(urlopen(req, timeout=8).read())
        latest = data.get("tag_name", "").lstrip("v")
        if latest and _ver_tuple(latest) > _ver_tuple(APP_VERSION):
            for asset in data.get("assets", []):
                if asset["name"].endswith(".exe") and "Setup" in asset["name"]:
                    _update_info["version"] = latest
                    _update_info["url"] = asset["browser_download_url"]
                    break
    except Exception:
        pass


threading.Thread(target=_check_for_update, daemon=True).start()


# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS audits (
            id                  TEXT PRIMARY KEY,
            contractor_name     TEXT,
            contract_number     TEXT,
            week_ending         TEXT,
            payroll_number      TEXT,
            submitted_at        TEXT,
            submitted_by        TEXT,
            overall_status      TEXT,
            pdf_filename        TEXT,
            pdf_path            TEXT,
            report_path         TEXT,
            worker_count        INTEGER,
            violation_count     INTEGER,
            warning_count       INTEGER,
            fringe_cash         REAL,
            fringe_plan         TEXT,
            fringe_plan_amt     REAL,
            fringe_plan_doc     TEXT DEFAULT '',
            apprentice_doc      TEXT DEFAULT '',
            wage_deduction_doc  TEXT DEFAULT ''
        )
    """)
    # Migrate existing DBs that predate the supp-doc columns
    for col in ("fringe_plan_doc", "apprentice_doc", "wage_deduction_doc"):
        try:
            conn.execute(f"ALTER TABLE audits ADD COLUMN {col} TEXT DEFAULT ''")
        except Exception:
            pass
    conn.commit()
    conn.close()


init_db()


# ---------------------------------------------------------------------------
# Audit runner
# ---------------------------------------------------------------------------

def run_full_audit(pdf_path, fringe_cash=0.0, fringe_plan_name="", fringe_plan_amount=0.0):
    """
    Run all audit modules against a WH-347 PDF.
    Manual fringe values override whatever was extracted from the PDF.
    Returns report_data dict.
    """
    parsed_data = extract_wh347_data(pdf_path)

    # Apply manual fringe overrides to every worker
    for worker in parsed_data.get("lines", []):
        if fringe_cash > 0:
            worker["fringe_paid_cash"] = fringe_cash
        if fringe_plan_name:
            worker["fringe_plan_name"] = fringe_plan_name
        if fringe_plan_amount > 0:
            worker["fringe_plan_amount"] = fringe_plan_amount

    wage_table         = load_wage_table(WAGE_TABLE)
    header_results     = audit_header(parsed_data)
    math_results       = audit_wh347_math(parsed_data)
    cwhssa_results     = audit_cwhssa(parsed_data)
    pay_results        = audit_all_workers(parsed_data, wage_table)
    fringe_results     = audit_fringe_benefits(parsed_data, wage_table)
    apprentice_results = audit_apprentice_rates(parsed_data, wage_table)
    deduction_results  = audit_deductions(parsed_data)
    class_results      = audit_classifications(parsed_data, wage_table)

    overall_pass = all([
        header_results.get("passed", True),
        math_results.get("passed", True),
        cwhssa_results.get("passed", True),
        pay_results.get("passed", True),
        fringe_results.get("passed", True),
        apprentice_results.get("passed", True),
        deduction_results.get("passed", True),
        class_results.get("passed", True),
    ])

    return {
        "parsed_data":  parsed_data,
        "header_audit": header_results,
        "math":         math_results,
        "cwhssa":       cwhssa_results,
        "pay":          pay_results,
        "fringe":       fringe_results,
        "apprentice":   apprentice_results,
        "deductions":   deduction_results,
        "classification": class_results,
        "passed":       overall_pass,
    }


def count_findings(report_data):
    """Returns (violation_count, warning_count) across all audit modules."""
    violations = 0
    warnings   = 0
    modules = ["header_audit", "math", "cwhssa", "pay", "fringe", "apprentice", "deductions", "classification"]
    for mod in modules:
        for entry in report_data.get(mod, {}).get("by_row", {}).values():
            result = entry.get("result", "")
            if result == "FAIL":
                violations += 1
            elif result == "WARN":
                warnings += 1
    return violations, warnings


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    conn = get_db()
    audits = conn.execute(
        "SELECT * FROM audits ORDER BY submitted_at DESC"
    ).fetchall()
    conn.close()

    total      = len(audits)
    total_fail = sum(1 for a in audits if a["overall_status"] == "FAIL")
    total_pass = sum(1 for a in audits if a["overall_status"] == "PASS")
    total_warn = sum(1 for a in audits if a["overall_status"] == "WARN")

    return render_template("index.html",
                           audits=audits,
                           total=total,
                           total_pass=total_pass,
                           total_fail=total_fail,
                           total_warn=total_warn,
                           wage_det=WAGE_DET_INFO)


def _accept_supp_pdf(field_name):
    """Save a supplementary PDF temporarily. Returns (tmp_path, original_filename)."""
    f = request.files.get(field_name)
    if f and f.filename and f.filename.lower().endswith(".pdf"):
        tmp_path = os.path.join(UPLOAD_DIR, f"tmp_{uuid.uuid4().hex[:8]}.pdf")
        f.save(tmp_path)
        return tmp_path, f.filename
    return None, ""


@app.route("/upload", methods=["POST"])
def upload():
    if "pdf" not in request.files:
        flash("No file selected.", "error")
        return redirect(url_for("index"))

    file = request.files["pdf"]
    if not file.filename:
        flash("No file selected.", "error")
        return redirect(url_for("index"))
    if not file.filename.lower().endswith(".pdf"):
        flash("Only PDF files are accepted.", "error")
        return redirect(url_for("index"))

    def safe_float(val, default=0.0):
        try:
            return float(val or 0)
        except (ValueError, TypeError):
            return default

    fringe_cash      = safe_float(request.form.get("fringe_cash"))
    fringe_plan_name = request.form.get("fringe_plan_name", "").strip()
    fringe_plan_amt  = safe_float(request.form.get("fringe_plan_amount"))
    submitted_by     = request.form.get("submitted_by", "").strip() or "Unknown"

    # Supplementary documents (processed then discarded — filenames stored for record)
    fringe_plan_path,    fringe_plan_fname    = _accept_supp_pdf("fringe_plan_pdf")
    apprentice_path,     apprentice_fname     = _accept_supp_pdf("apprentice_pdf")
    wage_deduction_path, wage_deduction_fname = _accept_supp_pdf("wage_deduction_pdf")

    # Save WH-347 PDF
    audit_id     = uuid.uuid4().hex[:10]
    pdf_filename = file.filename
    pdf_path     = os.path.join(UPLOAD_DIR, f"{audit_id}.pdf")
    report_path  = os.path.join(REPORT_DIR, f"{audit_id}.html")
    file.save(pdf_path)

    supp_docs = {
        "fringe_plan_doc":    fringe_plan_fname,
        "apprentice_doc":     apprentice_fname,
        "wage_deduction_doc": wage_deduction_fname,
    }

    try:
        report_data = run_full_audit(pdf_path, fringe_cash, fringe_plan_name, fringe_plan_amt)
        report_data["supp_docs"] = supp_docs
        generate_wh347_html_report(report_data, report_path)
    except Exception as e:
        os.remove(pdf_path)
        flash(f"Audit failed: {e}", "error")
        return redirect(url_for("index"))
    finally:
        # Supplementary PDFs are not stored permanently — delete after processing
        for p in (fringe_plan_path, apprentice_path, wage_deduction_path):
            if p and os.path.exists(p):
                try:
                    os.remove(p)
                except Exception:
                    pass

    header = report_data["parsed_data"].get("header", {})
    totals = report_data["parsed_data"].get("totals", {})
    v_count, w_count = count_findings(report_data)

    conn = get_db()
    conn.execute("""
        INSERT INTO audits (
            id, contractor_name, contract_number, week_ending, payroll_number,
            submitted_at, submitted_by, overall_status, pdf_filename, pdf_path,
            report_path, worker_count, violation_count, warning_count,
            fringe_cash, fringe_plan, fringe_plan_amt,
            fringe_plan_doc, apprentice_doc, wage_deduction_doc
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, (
        audit_id,
        header.get("contractor_name", "Unknown"),
        header.get("contract_number", ""),
        header.get("week_ending", ""),
        header.get("payroll_number", ""),
        datetime.now().strftime("%Y-%m-%d %H:%M"),
        submitted_by,
        "PASS" if (report_data["passed"] and w_count == 0) else ("WARN" if report_data["passed"] else "FAIL"),
        pdf_filename,
        pdf_path,
        report_path,
        totals.get("workers", 0),
        v_count,
        w_count,
        fringe_cash,
        fringe_plan_name,
        fringe_plan_amt,
        fringe_plan_fname,
        apprentice_fname,
        wage_deduction_fname,
    ))
    conn.commit()
    conn.close()

    return redirect(url_for("view_report", audit_id=audit_id))


@app.route("/report/<audit_id>")
def view_report(audit_id):
    conn = get_db()
    audit = conn.execute(
        "SELECT * FROM audits WHERE id = ?", (audit_id,)
    ).fetchone()
    conn.close()

    if not audit:
        flash("Audit not found.", "error")
        return redirect(url_for("index"))

    return render_template("report.html", audit=audit, audit_id=audit_id)


@app.route("/report/<audit_id>/raw")
def raw_report(audit_id):
    report_path = os.path.join(REPORT_DIR, f"{audit_id}.html")
    if not os.path.exists(report_path):
        return "Report not found", 404
    return send_file(report_path)


@app.route("/report/<audit_id>/pdf")
def download_pdf(audit_id):
    conn = get_db()
    audit = conn.execute(
        "SELECT * FROM audits WHERE id = ?", (audit_id,)
    ).fetchone()
    conn.close()
    if not audit or not os.path.exists(audit["pdf_path"]):
        return "PDF not found", 404
    return send_file(audit["pdf_path"],
                     download_name=audit["pdf_filename"],
                     as_attachment=True)


@app.route("/delete/<audit_id>", methods=["POST"])
def delete_audit(audit_id):
    conn = get_db()
    audit = conn.execute(
        "SELECT * FROM audits WHERE id = ?", (audit_id,)
    ).fetchone()

    if audit:
        for path_key in ("pdf_path", "report_path"):
            p = audit[path_key]
            if p and os.path.exists(p):
                os.remove(p)
        conn.execute("DELETE FROM audits WHERE id = ?", (audit_id,))
        conn.commit()
        flash("Audit deleted.", "info")

    conn.close()
    return redirect(url_for("index"))


@app.context_processor
def inject_update():
    return {
        "update_available": bool(_update_info.get("version")),
        "update_version":   _update_info.get("version", ""),
    }


@app.route("/do-update", methods=["POST"])
def do_update():
    url = _update_info.get("url")
    if not url:
        return jsonify({"error": "no update available"}), 400

    def _download_and_run():
        try:
            dest = os.path.join(tempfile.gettempdir(), "WH347-Audit-Engine-Setup.exe")
            urlretrieve(url, dest)
            subprocess.Popen([dest])
            import time, os as _os
            time.sleep(2)
            _os._exit(0)
        except Exception:
            pass

    threading.Thread(target=_download_and_run, daemon=False).start()
    return jsonify({"status": "downloading"})


# ---------------------------------------------------------------------------

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
