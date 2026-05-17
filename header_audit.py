"""
WH-347 Form Header and Statement of Compliance Audit
Validates that required form fields are present and properly completed.
Regulation: 29 CFR 5.5(a)(3)(ii)
"""

import re
from datetime import datetime


REQUIRED_FIELDS = [
    ("contractor_name",           "Contractor Name",              "29 CFR 5.5(a)(3)(ii)(A)"),
    ("contract_number",           "Contract Number",              "29 CFR 5.5(a)(3)(ii)(A)"),
    ("payroll_number",            "Payroll Number",               "29 CFR 5.5(a)(3)(ii)(A)"),
    ("week_ending",               "Week Ending Date",             "29 CFR 5.5(a)(3)(ii)(A)"),
    ("project_name",              "Project Name/Location",        "29 CFR 5.5(a)(3)(ii)(A)"),
    ("wage_determination_number", "Wage Determination Number",    "29 CFR 5.5(a)(3)(ii)(A)"),
]


def _is_valid_date(date_str):
    """Returns True if date_str can be parsed as a date."""
    if not date_str:
        return False
    for fmt in ("%m/%d/%Y", "%m/%d/%y", "%m-%d-%Y", "%m-%d-%y",
                "%Y-%m-%d", "%d/%m/%Y"):
        try:
            datetime.strptime(date_str.strip(), fmt)
            return True
        except ValueError:
            pass
    return False


def audit_header(parsed_data):
    """
    Validates the WH-347 form header for completeness and format.
    Also validates the Statement of Compliance certification block.

    Returns standard audit result dict.
    """

    header = parsed_data.get("header", {})
    compliance = parsed_data.get("compliance_statement", {})

    results = {
        "audit_name": "header",
        "passed": True,
        "checks": [],
        "by_row": {},
        "header_fields": [],
    }

    # --- Required header field checks ---
    for field_key, field_label, regulation in REQUIRED_FIELDS:
        value = str(header.get(field_key, "")).strip()
        present = bool(value and value.lower() not in ("", "none", "unknown"))

        if field_key == "week_ending":
            valid = _is_valid_date(value)
            if present and not valid:
                status = "WARN"
                reason = f"'{value}' does not appear to be a valid date"
                results["passed"] = False
            elif not present:
                status = "FAIL"
                reason = "Field missing or not extracted from PDF"
                results["passed"] = False
            else:
                status = "PASS"
                reason = ""
        elif field_key == "payroll_number":
            try:
                int(value)
                status = "PASS" if present else "FAIL"
                reason = "" if present else "Field missing"
            except (ValueError, TypeError):
                status = "WARN" if present else "FAIL"
                reason = "Value does not appear to be a numeric payroll number" if present else "Field missing"
                if not present:
                    results["passed"] = False
        else:
            if present:
                status = "PASS"
                reason = ""
            else:
                status = "WARN"  # WARN not FAIL — may be unextractable from PDF layout
                reason = "Field not found in extracted PDF text — verify manually"

        results["header_fields"].append({
            "field": field_label,
            "value": value or "(not found)",
            "status": status,
            "reason": reason,
            "regulation": regulation,
        })

        results["by_row"][field_key] = {
            "result": status,
            "reason": reason,
            "regulation": regulation,
            "severity": "VIOLATION" if status == "FAIL" else ("WARNING" if status == "WARN" else ""),
        }

        results["checks"].append({
            "row": field_key,
            "worker": "Form Header",
            "result": status,
            "details": reason or f"{field_label}: {value}",
            "regulation": regulation,
        })

    # --- Statement of Compliance check ---
    sig_status = "PASS" if compliance.get("certified_signature") else "WARN"
    sig_reason = (
        "" if compliance.get("certified_signature")
        else "Signature not detected — may be image-based; verify manually"
    )

    if not compliance.get("detected_by_text") and not compliance.get("certified_signature"):
        sig_reason = (
            "Statement of Compliance not found in extracted text. "
            "If this is a scanned/image PDF, verify signature manually."
        )

    results["header_fields"].append({
        "field": "Statement of Compliance",
        "value": (
            f"Certified by: {compliance.get('certified_name', 'N/A')} "
            f"({compliance.get('certified_title', 'N/A')}) "
            f"on {compliance.get('certified_date', 'N/A')}"
        ),
        "status": sig_status,
        "reason": sig_reason,
        "regulation": "29 CFR 5.5(a)(3)(ii)(B)",
    })

    results["by_row"]["compliance_statement"] = {
        "result": sig_status,
        "reason": sig_reason,
        "regulation": "29 CFR 5.5(a)(3)(ii)(B)",
        "severity": "WARNING" if sig_status == "WARN" else "",
    }

    results["checks"].append({
        "row": "compliance_statement",
        "worker": "Form Footer",
        "result": sig_status,
        "details": sig_reason or "Statement of Compliance found",
        "regulation": "29 CFR 5.5(a)(3)(ii)(B)",
    })

    return results
