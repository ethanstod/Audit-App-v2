from datetime import datetime
import os

# ---------------------------------------------------------------------------
# Regulation citation reference table
# ---------------------------------------------------------------------------
REGULATION_CITATIONS = [
    ("Davis-Bacon Act, 40 U.S.C. 3141–3148",
     "Base prevailing wage and fringe benefit requirement for federal contracts"),
    ("29 CFR 5.5(a)(1)(i)",
     "Workers must be paid at least the wage rates for their classification"),
    ("29 CFR 5.5(a)(1)(ii)",
     "Fringe benefit credit requirements — cash or bona fide plan"),
    ("29 CFR 5.5(a)(3)(ii)",
     "Certified payroll submission requirements — WH-347 form"),
    ("29 CFR 5.5(a)(4)",
     "Apprentice and trainee wage rates and ratios"),
    ("40 U.S.C. 3702 (CWHSSA)",
     "Overtime at 1.5× base rate for hours over 40 on covered contracts"),
    ("29 CFR 5.8",
     "CWHSSA liquidated damages — $31 per calendar day per affected worker"),
    ("Copeland Anti-Kickback Act, 18 U.S.C. 874; 29 CFR 3.1",
     "Prohibition on kickbacks — workers cannot be required to return wages"),
    ("29 CFR 3.5",
     "Permissible payroll deduction types — unauthorized deductions prohibited"),
    ("EO 14026; 29 CFR 10.28",
     "Minimum wage $17.75/hr (2025) for contracts awarded after Jan 30, 2022"),
]


# ---------------------------------------------------------------------------
# Helper utilities
# ---------------------------------------------------------------------------

def _badge(result):
    colors = {
        "PASS": ("#d4edda", "#155724", "PASS"),
        "FAIL": ("#f8d7da", "#721c24", "FAIL"),
        "WARN": ("#fff3cd", "#856404", "WARN"),
    }
    bg, fg, label = colors.get(result, ("#e2e3e5", "#383d41", result))
    return (f'<span style="background:{bg};color:{fg};padding:3px 8px;'
            f'border-radius:4px;font-weight:bold;font-size:12px;">{label}</span>')


def _overall_badge(passed):
    if passed:
        return ('<span style="background:#28a745;color:white;padding:6px 16px;'
                'border-radius:6px;font-size:18px;font-weight:bold;">PASS</span>')
    return ('<span style="background:#dc3545;color:white;padding:6px 16px;'
            'border-radius:6px;font-size:18px;font-weight:bold;">FAIL</span>')


def _combine_row_status(row_number, audit_results_list):
    """Combines results from all audit modules for a given row number."""
    combined = "PASS"
    reasons = []
    regulations = []
    required_base_rate = None
    required_fringe = None
    back_wages = 0.0

    for audit in audit_results_list:
        by_row = audit.get("by_row", {})
        if row_number not in by_row:
            continue
        entry = by_row[row_number]
        result = entry.get("result", "PASS")
        if result == "FAIL":
            combined = "FAIL"
        elif result == "WARN" and combined != "FAIL":
            combined = "WARN"
        if entry.get("reason"):
            reasons.append(f"[{audit.get('audit_name', '?').upper()}] {entry['reason']}")
        if entry.get("regulation"):
            regulations.append(entry["regulation"])
        # Pull required rates and back-wages estimate from the pay audit entry
        if audit.get("audit_name") == "pay":
            if entry.get("required_base_rate") is not None:
                required_base_rate = entry["required_base_rate"]
            if entry.get("required_fringe") is not None:
                required_fringe = entry["required_fringe"]
            back_wages += float(entry.get("back_wages_estimate", 0.0))

    return (combined, " | ".join(reasons), "; ".join(set(regulations)),
            required_base_rate, required_fringe, back_wages)


def _fmt(val, prefix="$"):
    try:
        f = float(val)
        if f == 0.0:
            return "—"
        return f"{prefix}{f:.2f}"
    except (TypeError, ValueError):
        return str(val) if val else "—"


# ---------------------------------------------------------------------------
# Report sections
# ---------------------------------------------------------------------------

def _section_summary(parsed_data, report_data, timestamp):
    header = parsed_data.get("header", {})
    totals = parsed_data.get("totals", {})
    overall_pass = report_data.get("passed", False)

    cwhssa = report_data.get("cwhssa", {})
    ld_estimate = cwhssa.get("total_liquidated_damages_estimate", 0.0)

    audit_modules = ["header_audit", "sanity", "math", "cwhssa", "pay", "fringe",
                     "apprentice", "deductions", "classification"]
    module_statuses = []
    for m in audit_modules:
        res = report_data.get(m, {})
        if res:
            status = "PASS" if res.get("passed", True) else "FAIL"
            module_statuses.append((m.replace("_", " ").upper(), status))

    module_rows = "".join(
        f"<tr><td>{name}</td><td>{_badge(status)}</td></tr>"
        for name, status in module_statuses
    )

    ld_row = ""
    if ld_estimate > 0:
        ld_row = (f'<tr><td colspan="2" style="color:#dc3545;font-weight:bold;">'
                  f'⚠ Estimated CWHSSA Liquidated Damages Exposure: '
                  f'${ld_estimate:.2f}/day (29 CFR 5.8)</td></tr>')

    return f"""
    <section>
        <h2>1. Audit Summary</h2>
        <table class="summary-table">
            <tr><td><strong>Overall Status</strong></td>
                <td>{_overall_badge(overall_pass)}</td></tr>
            <tr><td>Audit Run</td><td>{timestamp}</td></tr>
            <tr><td>Week Ending</td>
                <td>{header.get('week_ending', '(not extracted)')}</td></tr>
            <tr><td>Payroll Number</td>
                <td>{header.get('payroll_number', '(not extracted)')}</td></tr>
            <tr><td>Contractor</td>
                <td>{header.get('contractor_name', '(not extracted)')}</td></tr>
            <tr><td>Contract Number</td>
                <td>{header.get('contract_number', '(not extracted)')}</td></tr>
            <tr><td>Project</td>
                <td>{header.get('project_name', '(not extracted)')}</td></tr>
            <tr><td>Total Workers</td><td>{totals.get('workers', 0)}</td></tr>
            <tr><td>Journeymen / Apprentices</td>
                <td>{totals.get('journeymen', 0)} / {totals.get('apprentices', 0)}</td></tr>
            <tr><td>Total Gross Payroll</td>
                <td>${totals.get('total_gross', 0):.2f}</td></tr>
            {ld_row}
        </table>
        <br>
        <table class="summary-table">
            <tr><th>Audit Module</th><th>Result</th></tr>
            {module_rows}
        </table>
    </section>
    """


def _section_header_audit(header_audit):
    if not header_audit:
        return ""

    fields = header_audit.get("header_fields", [])
    rows = ""
    for f in fields:
        rows += f"""
        <tr>
            <td>{f['field']}</td>
            <td style="font-family:monospace">{f['value']}</td>
            <td>{_badge(f['status'])}</td>
            <td style="font-size:12px;color:#666;">{f.get('reason', '')}</td>
            <td style="font-size:11px;color:#888;">{f.get('regulation', '')}</td>
        </tr>"""

    return f"""
    <section>
        <h2>2. Form Header &amp; Statement of Compliance</h2>
        <table>
            <tr>
                <th>Field</th>
                <th>Extracted Value</th>
                <th>Status</th>
                <th>Notes</th>
                <th>Regulation</th>
            </tr>
            {rows}
        </table>
    </section>
    """


def _section_worker_detail(workers, audit_results_list):
    if not workers:
        return ""

    rows = ""
    total_back_wages = 0.0
    for w in workers:
        row_no = w.get("row_number")
        combined, reasons, regulations, req_base, req_fringe, back_wages = _combine_row_status(
            row_no, audit_results_list
        )
        total_back_wages += back_wages

        reason_html = ""
        if reasons:
            reason_html = (f'<div style="font-size:11px;color:#666;margin-top:4px;">'
                           f'{reasons}</div>')
        reg_html = ""
        if regulations:
            reg_html = (f'<div style="font-size:10px;color:#999;">'
                        f'{regulations}</div>')

        j_ra_label = w.get("j_ra", "")
        j_ra_color = "#856404" if j_ra_label == "RA" else "#155724"

        reported_base = float(w.get("st_rate", w.get("rate", 0)))
        reported_fringe_cash = float(w.get("fringe_paid_cash", 0))

        # Highlight rate cell red when reported < required
        rate_style = ""
        fringe_style = ""
        if req_base is not None and reported_base < req_base - 0.02:
            rate_style = "background:#f8d7da;font-weight:bold;"
        if req_fringe is not None and reported_fringe_cash < req_fringe - 0.02:
            fringe_style = "background:#f8d7da;font-weight:bold;"

        req_base_cell   = f"${req_base:.2f}" if req_base is not None else "—"
        req_fringe_cell = f"${req_fringe:.2f}" if req_fringe is not None else "—"
        back_wages_cell = f'<span style="color:#dc3545;font-weight:bold">${back_wages:.2f}</span>' if back_wages > 0 else "—"

        rows += f"""
        <tr>
            <td>{row_no}</td>
            <td>{w.get('last_name')}, {w.get('first_name')}</td>
            <td style="font-size:12px">{w.get('classification', '—')}</td>
            <td style="color:{j_ra_color};font-weight:bold">{j_ra_label}</td>
            <td>{w.get('st_hours', 0)}</td>
            <td>{w.get('ot_hours', 0)}</td>
            <td>{w.get('dt_hours', 0)}</td>
            <td>{w.get('total_hours', 0)}</td>
            <td style="{rate_style}">{_fmt(reported_base)}</td>
            <td style="font-size:11px;color:#888">{req_base_cell}</td>
            <td>{_fmt(w.get('ot_rate', 0))}</td>
            <td>{_fmt(w.get('gross', 0))}</td>
            <td style="{fringe_style}">{_fmt(reported_fringe_cash)}</td>
            <td style="font-size:11px;color:#888">{req_fringe_cell}</td>
            <td>{_fmt(w.get('deductions', 0))}</td>
            <td>{_fmt(w.get('net', 0))}</td>
            <td>{back_wages_cell}</td>
            <td>{_badge(combined)}{reason_html}{reg_html}</td>
        </tr>"""

    bw_summary = ""
    if total_back_wages > 0:
        bw_summary = (f'<p style="color:#dc3545;font-weight:bold;margin-top:8px;">'
                      f'Estimated Total Back-Wages Owed: ${total_back_wages:.2f} '
                      f'(base shortfall × weighted hours + fringe shortfall × total hours)</p>')

    return f"""
    <section>
        <h2>3. Worker Detail</h2>
        <p style="font-size:12px;color:#666;">
            <span style="background:#f8d7da;padding:2px 6px;border-radius:3px;">Red cells</span>
            indicate reported value is below the prevailing wage requirement.
            &ldquo;Req. Base&rdquo; and &ldquo;Req. Fringe&rdquo; show the wage determination amounts.
            &ldquo;Back-Wages&rdquo; is an estimate of wages owed per worker this payroll period.
        </p>
        {bw_summary}
        <div style="overflow-x:auto">
        <table>
            <tr>
                <th>#</th>
                <th>Worker</th>
                <th>Classification</th>
                <th>J/RA</th>
                <th>ST Hrs</th>
                <th>OT Hrs</th>
                <th>DT Hrs</th>
                <th>Total Hrs</th>
                <th>ST Rate</th>
                <th>Req. Base</th>
                <th>OT Rate</th>
                <th>Gross</th>
                <th>Fringe Cash</th>
                <th>Req. Fringe</th>
                <th>Deductions</th>
                <th>Net</th>
                <th>Back-Wages Est.</th>
                <th>Audit Status</th>
            </tr>
            {rows}
        </table>
        </div>
    </section>
    """


def _section_violations(audit_results_list):
    violations = []
    for audit in audit_results_list:
        name = audit.get("audit_name", "").upper()
        for row, entry in audit.get("by_row", {}).items():
            if entry.get("result") in ("FAIL", "WARN"):
                violations.append({
                    "module": name,
                    "row": row,
                    "result": entry.get("result"),
                    "reason": entry.get("reason", ""),
                    "regulation": entry.get("regulation", ""),
                    "severity": entry.get("severity", ""),
                })

    if not violations:
        return """
        <section>
            <h2>4. Violations &amp; Warnings</h2>
            <p style="color:#28a745;font-weight:bold;">✓ No violations or warnings found.</p>
        </section>
        """

    rows = ""
    for v in violations:
        rows += f"""
        <tr>
            <td style="font-weight:bold">{v['module']}</td>
            <td>{v['row']}</td>
            <td>{_badge(v['result'])}</td>
            <td style="font-size:12px">{v['reason']}</td>
            <td style="font-size:11px;color:#888">{v['regulation']}</td>
        </tr>"""

    return f"""
    <section>
        <h2>4. Violations &amp; Warnings ({len(violations)} finding(s))</h2>
        <table>
            <tr>
                <th>Audit Module</th>
                <th>Row / Field</th>
                <th>Result</th>
                <th>Finding</th>
                <th>Regulation</th>
            </tr>
            {rows}
        </table>
    </section>
    """


def _section_apprentice_ratios(apprentice_results):
    ratio_summary = (apprentice_results or {}).get("ratio_summary", {})
    if not ratio_summary:
        return ""

    rows = ""
    for trade, data in ratio_summary.items():
        rows += f"""
        <tr>
            <td>{data.get('trade', trade)}</td>
            <td>{data.get('journeymen', 0)}</td>
            <td>{data.get('apprentices', 0)}</td>
            <td>{data.get('allowed_ratio', 'N/A')}</td>
            <td>{_badge(data.get('status', 'PASS'))}</td>
            <td style="font-size:12px">{data.get('reason', '')}</td>
        </tr>"""

    return f"""
    <section>
        <h2>5. Apprentice / Journeyman Ratio Summary</h2>
        <table>
            <tr>
                <th>Trade Classification</th>
                <th>Journeymen</th>
                <th>Apprentices</th>
                <th>Allowed Ratio</th>
                <th>Status</th>
                <th>Notes</th>
            </tr>
            {rows}
        </table>
        <p style="font-size:12px;color:#666;">
            Regulation: 29 CFR 5.5(a)(4)
        </p>
    </section>
    """


def _section_regulation_reference():
    rows = "".join(
        f"<tr><td style='font-family:monospace;font-size:12px'>{cite}</td>"
        f"<td style='font-size:12px'>{desc}</td></tr>"
        for cite, desc in REGULATION_CITATIONS
    )
    return f"""
    <section>
        <h2>6. Regulatory Reference</h2>
        <table>
            <tr><th>Citation</th><th>Description</th></tr>
            {rows}
        </table>
    </section>
    """


# ---------------------------------------------------------------------------
# Main report generator
# ---------------------------------------------------------------------------

def generate_wh347_html_report(report_data, output_path=None):
    """
    Generates a multi-section DOL-quality HTML audit report.

    report_data keys:
        parsed_data, header_audit, math, cwhssa, pay, fringe,
        apprentice, deductions, classification, passed
    """

    parsed_data = report_data.get("parsed_data", {})
    workers = parsed_data.get("lines", [])
    overall_pass = report_data.get("passed", False)
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    if output_path is None:
        output_path = os.path.join(os.getcwd(), "report_wh347.html")

    # All audit result dicts in a list (for per-row combination)
    audit_results_list = [
        r for r in [
            report_data.get("sanity"),
            report_data.get("math"),
            report_data.get("cwhssa"),
            report_data.get("pay"),
            report_data.get("fringe"),
            report_data.get("apprentice"),
            report_data.get("deductions"),
            report_data.get("classification"),
        ] if r is not None
    ]

    # Build sections
    sec1 = _section_summary(parsed_data, report_data, timestamp)
    sec2 = _section_header_audit(report_data.get("header_audit"))
    sec3 = _section_worker_detail(workers, audit_results_list)
    sec4 = _section_violations(audit_results_list)
    sec5 = _section_apprentice_ratios(report_data.get("apprentice"))
    sec6 = _section_regulation_reference()

    overall_color = "#28a745" if overall_pass else "#dc3545"
    overall_label = "PASS" if overall_pass else "FAIL"

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>WH-347 Davis-Bacon Compliance Audit Report</title>
    <style>
        body {{
            font-family: Arial, sans-serif;
            background: #f8f9fa;
            color: #212529;
            margin: 0;
            padding: 20px;
        }}
        .header-bar {{
            background: #1a1a2e;
            color: white;
            padding: 20px 30px;
            border-radius: 8px;
            margin-bottom: 24px;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }}
        .header-bar h1 {{
            margin: 0;
            font-size: 22px;
        }}
        .header-bar .subtitle {{
            font-size: 13px;
            color: #adb5bd;
            margin-top: 4px;
        }}
        .overall-status {{
            background: {overall_color};
            color: white;
            padding: 10px 24px;
            border-radius: 8px;
            font-size: 20px;
            font-weight: bold;
            letter-spacing: 2px;
        }}
        section {{
            background: white;
            border-radius: 8px;
            padding: 20px 24px;
            margin-bottom: 20px;
            box-shadow: 0 1px 4px rgba(0,0,0,0.08);
        }}
        section h2 {{
            margin-top: 0;
            font-size: 16px;
            color: #1a1a2e;
            border-bottom: 2px solid #e9ecef;
            padding-bottom: 8px;
        }}
        table {{
            width: 100%;
            border-collapse: collapse;
            font-size: 13px;
        }}
        th, td {{
            border: 1px solid #dee2e6;
            padding: 8px 10px;
            text-align: left;
            vertical-align: top;
        }}
        th {{
            background: #f1f3f5;
            font-weight: 600;
            color: #495057;
        }}
        tr:nth-child(even) {{
            background: #f8f9fa;
        }}
        .summary-table {{
            max-width: 600px;
        }}
        .summary-table td:first-child {{
            font-weight: 600;
            color: #495057;
            width: 200px;
        }}
        @media print {{
            body {{ background: white; padding: 0; }}
            .header-bar {{ background: #1a1a2e !important; -webkit-print-color-adjust: exact; }}
        }}
    </style>
</head>
<body>
    <div class="header-bar">
        <div>
            <h1>WH-347 Davis-Bacon Compliance Audit Report</h1>
            <div class="subtitle">
                U.S. Department of Labor — Davis-Bacon and Related Acts (DBRA)
                &nbsp;|&nbsp; Generated: {timestamp}
            </div>
        </div>
        <div class="overall-status">{overall_label}</div>
    </div>

    {sec1}
    {sec2}
    {sec3}
    {sec4}
    {sec5}
    {sec6}

    <footer style="text-align:center;color:#adb5bd;font-size:11px;margin-top:30px;padding:10px;">
        WH-347 Federal Compliance Audit Engine &nbsp;|&nbsp;
        This report is for compliance review purposes only.
        All findings should be verified by a qualified compliance officer.
    </footer>
</body>
</html>
"""

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)

    return output_path
