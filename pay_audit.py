import pandas as pd
import os
import re
from difflib import get_close_matches

# Federal minimum wage (EO 14026, effective 2025 for new contracts)
EO_14026_MINIMUM_WAGE = 17.75

TOLERANCE = 0.02


# ---------------------------------------------------------------------------
# Fringe cell parser
# ---------------------------------------------------------------------------

def parse_fringe_cell(value):
    """
    Parses DOL wage determination fringe formats:
      "16.56"       -> flat=16.56, pct=0.0
      "3%+24.18"    -> flat=24.18, pct=0.03
      "22.45+3%"    -> flat=22.45, pct=0.03
      ""            -> flat=0.0,   pct=0.0
    Returns (flat_amount, percent_as_decimal)
    """
    value = str(value).strip().replace("$", "").replace(",", "")
    if not value or value.lower() in ("nan", "none", ""):
        return 0.0, 0.0

    # Format: pct%+flat  OR flat+pct%
    pct_plus_flat = re.search(r"(\d+(?:\.\d+)?)\%\+(\d+(?:\.\d+)?)", value)
    flat_plus_pct = re.search(r"(\d+(?:\.\d+)?)\+(\d+(?:\.\d+)?)\%", value)

    if pct_plus_flat:
        return float(pct_plus_flat.group(2)), float(pct_plus_flat.group(1)) / 100.0
    if flat_plus_pct:
        return float(flat_plus_pct.group(1)), float(flat_plus_pct.group(2)) / 100.0

    # Plain number
    try:
        return float(re.sub(r"[^\d.]", "", value)), 0.0
    except (ValueError, TypeError):
        return 0.0, 0.0


# ---------------------------------------------------------------------------
# Wage table loader
# ---------------------------------------------------------------------------

def load_wage_table(path):
    """
    Loads the prevailing wage rate Excel file.

    Expected columns (case-insensitive):
      CLASSIFICATION, BASE_RATE, FRINGE (handles "16.56" or "3%+24.18"),
      APPRENTICE_PROGRAM, APPRENTICE_PERIOD_1_PCT ... _4_PCT,
      APPRENTICE_RATIO_NUM, APPRENTICE_RATIO_DEN,
      WAGE_DET_NUMBER, EFFECTIVE_DATE, CONSTRUCTION_TYPE
    """
    if not os.path.exists(path):
        print("[!] Wage table not found.")
        return pd.DataFrame()

    try:
        df = pd.read_excel(path)
    except Exception as e:
        print(f"[ERROR] Failed to load wage table: {e}")
        return pd.DataFrame()

    df.columns = [c.strip().upper().replace(" ", "_") for c in df.columns]

    # Detect required columns with fallback names
    col_aliases = {
        "CLASSIFICATION": ["CLASSIFICATION", "CLASS", "TRADE", "DESCRIPTION"],
        "BASE_RATE":      ["BASE_RATE", "BASE", "RATE", "HOURLY_RATE", "WAGE"],
        "FRINGE":         ["FRINGE", "FRINGE_RATE", "BENEFITS", "FRINGE_BENEFITS"],
    }

    resolved = {}
    for target, aliases in col_aliases.items():
        for alias in aliases:
            if alias in df.columns:
                resolved[target] = alias
                break

    if "CLASSIFICATION" not in resolved or "BASE_RATE" not in resolved:
        print("[!] Could not detect required CLASSIFICATION or BASE_RATE columns.")
        print(f"   Found columns: {list(df.columns)}")
        return pd.DataFrame()

    df["CLASSIFICATION"] = df[resolved["CLASSIFICATION"]].astype(str).str.upper().str.strip()
    df["BASE_RATE"] = pd.to_numeric(df[resolved["BASE_RATE"]], errors="coerce")
    df = df.dropna(subset=["BASE_RATE"])

    if "FRINGE" in resolved:
        parsed_fringe = df[resolved["FRINGE"]].apply(parse_fringe_cell)
        df["FRINGE_FLAT"] = parsed_fringe.apply(lambda x: x[0])
        df["FRINGE_PCT"] = parsed_fringe.apply(lambda x: x[1])
    else:
        df["FRINGE_FLAT"] = 0.0
        df["FRINGE_PCT"] = 0.0

    # Apprentice columns (optional)
    for col in ["APPRENTICE_PROGRAM", "APPRENTICE_PERIOD_1_PCT", "APPRENTICE_PERIOD_2_PCT",
                "APPRENTICE_PERIOD_3_PCT", "APPRENTICE_PERIOD_4_PCT",
                "APPRENTICE_RATIO_NUM", "APPRENTICE_RATIO_DEN"]:
        if col not in df.columns:
            df[col] = None

    df["APPRENTICE_RATIO_NUM"] = pd.to_numeric(df["APPRENTICE_RATIO_NUM"], errors="coerce").fillna(1)
    df["APPRENTICE_RATIO_DEN"] = pd.to_numeric(df["APPRENTICE_RATIO_DEN"], errors="coerce").fillna(1)

    keep = ["CLASSIFICATION", "BASE_RATE", "FRINGE_FLAT", "FRINGE_PCT",
            "APPRENTICE_PROGRAM", "APPRENTICE_PERIOD_1_PCT", "APPRENTICE_PERIOD_2_PCT",
            "APPRENTICE_PERIOD_3_PCT", "APPRENTICE_PERIOD_4_PCT",
            "APPRENTICE_RATIO_NUM", "APPRENTICE_RATIO_DEN"]

    return df[[c for c in keep if c in df.columns]].reset_index(drop=True)


# ---------------------------------------------------------------------------
# Classification matching helper
# ---------------------------------------------------------------------------

def find_wage_row(classification, wage_table):
    """
    Fuzzy-matches a worker's classification against the wage table.
    Returns the matching row as a dict, or None.
    """
    if wage_table.empty:
        return None

    wage_classes = wage_table["CLASSIFICATION"].tolist()
    classification_upper = str(classification).upper().strip()

    # Exact match first
    exact = wage_table[wage_table["CLASSIFICATION"] == classification_upper]
    if not exact.empty:
        return exact.iloc[0].to_dict()

    # Fuzzy match
    matches = get_close_matches(classification_upper, wage_classes, n=1, cutoff=0.75)
    if not matches:
        return None

    row = wage_table[wage_table["CLASSIFICATION"] == matches[0]].iloc[0].to_dict()
    row["_fuzzy_match"] = matches[0]
    return row


# ---------------------------------------------------------------------------
# Base rate + fringe audit
# ---------------------------------------------------------------------------

def audit_all_workers(parsed_data, wage_table):
    """
    Validates reported base rate >= required prevailing wage base rate.
    Also checks total compensation (base + fringe) >= required total package.
    Regulation: 29 CFR 5.5(a)(1)(i); Davis-Bacon Act Sec. 1
    """

    workers = parsed_data.get("lines", [])
    results = {
        "audit_name": "pay",
        "passed": True,
        "checks": [],
        "by_row": {}
    }

    if wage_table.empty:
        print("[!] No wage table loaded -- skipping pay audit.")
        return results

    for worker in workers:
        row = worker.get("row_number")
        classification = worker.get("classification", "")
        st_rate = float(worker.get("st_rate", worker.get("rate", 0)))
        fringe_cash = float(worker.get("fringe_paid_cash", 0))
        fringe_plan = float(worker.get("fringe_plan_amount", 0))
        reported_fringe = fringe_cash + fringe_plan
        reported_total = round(st_rate + reported_fringe, 2)

        wage_row = find_wage_row(classification, wage_table)

        if wage_row is None:
            results["by_row"][row] = {
                "result": "WARN",
                "reason": f"No wage table match for classification '{classification}'",
                "regulation": "29 CFR 5.5(a)(1)(i)",
                "severity": "WARNING",
            }
            results["checks"].append({
                "row": row,
                "result": "WARN",
                "details": f"No classification match for '{classification}'",
                "regulation": "29 CFR 5.5(a)(1)(i)",
            })
            continue

        required_base = float(wage_row["BASE_RATE"])
        fuzzy_note = f" (matched to '{wage_row.get('_fuzzy_match', classification)}')" \
                     if "_fuzzy_match" in wage_row else ""
        issues = []

        # Check base rate
        if st_rate < required_base - TOLERANCE:
            issues.append(
                f"Base rate ${st_rate:.2f} < required ${required_base:.2f}{fuzzy_note}"
            )

        # Check total compensation
        fringe_flat = float(wage_row.get("FRINGE_FLAT", 0))
        fringe_pct = float(wage_row.get("FRINGE_PCT", 0))
        required_fringe = round(fringe_flat + (required_base * fringe_pct), 2)
        required_total = round(required_base + required_fringe, 2)

        if required_fringe > 0 and reported_total < required_total - TOLERANCE:
            issues.append(
                f"Total compensation ${reported_total:.2f}/hr "
                f"< required ${required_total:.2f}/hr "
                f"(base ${required_base:.2f} + fringe ${required_fringe:.2f}){fuzzy_note}"
            )

        if issues:
            results["passed"] = False
            results["by_row"][row] = {
                "result": "FAIL",
                "reason": " | ".join(issues),
                "regulation": "29 CFR 5.5(a)(1)(i); Davis-Bacon Act Sec. 1",
                "severity": "VIOLATION",
            }
        else:
            results["by_row"][row] = {
                "result": "PASS",
                "reason": fuzzy_note.strip(" ()") if fuzzy_note else "",
                "regulation": "29 CFR 5.5(a)(1)(i)",
                "severity": "",
            }

        results["checks"].append({
            "row": row,
            "result": results["by_row"][row]["result"],
            "details": results["by_row"][row]["reason"] or "OK",
            "regulation": "29 CFR 5.5(a)(1)(i)",
        })

    return results


# ---------------------------------------------------------------------------
# Apprentice rate and ratio audit
# ---------------------------------------------------------------------------

def audit_apprentice_rates(parsed_data, wage_table):
    """
    For each Registered Apprentice (j_ra == 'RA'):
    - Checks reported rate >= journeyman_rate × apprentice_period_pct
    - Checks apprentice:journeyman ratio per trade does not exceed allowed ratio

    Regulation: 29 CFR 5.5(a)(4)
    """

    workers = parsed_data.get("lines", [])
    results = {
        "audit_name": "apprentice",
        "passed": True,
        "checks": [],
        "by_row": {},
        "ratio_summary": {},
    }

    if wage_table.empty:
        return results

    # Group by trade for ratio check
    trade_journeymen = {}
    trade_apprentices = {}

    for worker in workers:
        trade = worker.get("classification", "UNKNOWN").upper()
        j_ra = worker.get("j_ra", "").upper()
        if j_ra == "J":
            trade_journeymen[trade] = trade_journeymen.get(trade, 0) + 1
        elif j_ra == "RA":
            trade_apprentices[trade] = trade_apprentices.get(trade, 0) + 1

    # Per-worker apprentice rate checks
    for worker in workers:
        row = worker.get("row_number")
        j_ra = worker.get("j_ra", "").upper()

        if j_ra != "RA":
            continue

        classification = worker.get("classification", "")
        st_rate = float(worker.get("st_rate", worker.get("rate", 0)))
        period = int(worker.get("apprentice_period", 1) or 1)
        issues = []

        wage_row = find_wage_row(classification, wage_table)

        if wage_row is None:
            results["by_row"][row] = {
                "result": "WARN",
                "reason": f"No wage table entry for apprentice classification '{classification}'",
                "regulation": "29 CFR 5.5(a)(4)",
                "severity": "WARNING",
            }
            results["checks"].append({
                "row": row,
                "result": "WARN",
                "details": f"No wage table match for '{classification}'",
                "regulation": "29 CFR 5.5(a)(4)",
            })
            continue

        journeyman_rate = float(wage_row["BASE_RATE"])

        # Check apprentice rate for their period
        pct_col = f"APPRENTICE_PERIOD_{period}_PCT"
        apprentice_pct = wage_row.get(pct_col)

        if apprentice_pct is not None:
            try:
                apprentice_pct = float(apprentice_pct)
                required_rate = round(journeyman_rate * apprentice_pct, 2)
                if st_rate < required_rate - TOLERANCE:
                    issues.append(
                        f"Apprentice rate ${st_rate:.2f} < required ${required_rate:.2f} "
                        f"({int(apprentice_pct * 100)}% of journeyman ${journeyman_rate:.2f})"
                    )
            except (ValueError, TypeError):
                pass

        if issues:
            results["passed"] = False
            results["by_row"][row] = {
                "result": "FAIL",
                "reason": " | ".join(issues),
                "regulation": "29 CFR 5.5(a)(4)",
                "severity": "VIOLATION",
            }
        else:
            results["by_row"][row] = {
                "result": "PASS",
                "reason": "",
                "regulation": "29 CFR 5.5(a)(4)",
                "severity": "",
            }

        results["checks"].append({
            "row": row,
            "result": results["by_row"][row]["result"],
            "details": results["by_row"][row]["reason"] or "OK",
            "regulation": "29 CFR 5.5(a)(4)",
        })

    # Ratio check per trade
    all_trades = set(list(trade_journeymen.keys()) + list(trade_apprentices.keys()))
    for trade in all_trades:
        jmen = trade_journeymen.get(trade, 0)
        apps = trade_apprentices.get(trade, 0)

        if apps == 0:
            continue

        wage_row = find_wage_row(trade, wage_table)
        ratio_num = int(wage_row.get("APPRENTICE_RATIO_NUM", 1)) if wage_row else 1
        ratio_den = int(wage_row.get("APPRENTICE_RATIO_DEN", 1)) if wage_row else 1

        if jmen == 0:
            ratio_status = "WARN"
            ratio_reason = f"Apprentices in '{trade}' but no journeymen found on this payroll"
        else:
            # Max allowed apprentices = floor(jmen * ratio_num / ratio_den)
            max_allowed = max(1, int(jmen * ratio_num / ratio_den))
            if apps > max_allowed:
                ratio_status = "FAIL"
                ratio_reason = (
                    f"Ratio violation: {apps} apprentice(s) to {jmen} journeyman(men) "
                    f"exceeds allowed {ratio_num}:{ratio_den} ratio "
                    f"(max {max_allowed} apprentice(s))"
                )
                results["passed"] = False
            else:
                ratio_status = "PASS"
                ratio_reason = f"{apps}:{jmen} within allowed {ratio_num}:{ratio_den}"

        results["ratio_summary"][trade] = {
            "trade": trade,
            "journeymen": jmen,
            "apprentices": apps,
            "allowed_ratio": f"{ratio_num}:{ratio_den}",
            "status": ratio_status,
            "reason": ratio_reason,
        }

    return results


# ---------------------------------------------------------------------------
# Deduction / Copeland Act audit
# ---------------------------------------------------------------------------

def audit_deductions(parsed_data, authorized_deductions=None):
    """
    Checks deduction amounts for compliance with Copeland Anti-Kickback Act.

    Checks:
    - Net pay >= $0 (hard violation)
    - Net pay >= EO minimum wage × total hours (minimum wage floor)
    - Deductions <= 85% of gross (excessive deductions flag)
    - If an authorized deduction doc is on file for this worker, reported
      deductions must match the authorized amount within tolerance

    authorized_deductions: {worker_name: authorized_amount} — keyed by the
    name entered when the wage deduction doc was uploaded.

    Regulation: Copeland Anti-Kickback Act; 29 CFR 3.1; 29 CFR 3.5; EO 14026
    """
    authorized_deductions = authorized_deductions or {}

    workers = parsed_data.get("lines", [])
    results = {
        "audit_name": "deductions",
        "passed": True,
        "checks": [],
        "by_row": {},
    }

    for worker in workers:
        row = worker.get("row_number")
        gross = float(worker.get("gross", 0))
        deductions = float(worker.get("deductions", 0))
        net = float(worker.get("net", 0))
        total_hours = float(worker.get("total_hours", 0))
        issues = []

        # Check 1: Net must not be negative
        if net < 0.0:
            issues.append({
                "text": f"Net pay is negative (${net:.2f}) — potential kickback violation",
                "regulation": "Copeland Anti-Kickback Act; 29 CFR 3.1",
                "severity": "VIOLATION",
            })

        # Check 2: Net >= EO minimum wage floor
        if total_hours > 0:
            min_floor = round(EO_14026_MINIMUM_WAGE * total_hours, 2)
            if net < min_floor - TOLERANCE:
                issues.append({
                    "text": f"Net pay ${net:.2f} is below EO 14026 minimum wage floor "
                            f"${min_floor:.2f} (${EO_14026_MINIMUM_WAGE}/hr × {total_hours} hrs)",
                    "regulation": "EO 14026; 29 CFR 10.28",
                    "severity": "VIOLATION",
                })

        # Check 3: Excessive deductions (heuristic flag)
        if gross > 0 and deductions > gross * 0.85:
            issues.append({
                "text": f"Deductions ${deductions:.2f} exceed 85% of gross ${gross:.2f} "
                        f"— verify authorization per 29 CFR 3.5",
                "regulation": "29 CFR 3.5",
                "severity": "WARNING",
            })

        # Check 4: Cross-reference authorization document
        # If a wage deduction doc was uploaded for this worker, the reported
        # deduction amount must match the authorized amount on file.
        if authorized_deductions and deductions > 0:
            full_name = (
                f"{worker.get('first_name', '')} {worker.get('last_name', '')}".strip().upper()
            )
            last_name = worker.get('last_name', '').strip().upper()

            auth_amount = None
            matched_key = None
            for name_key, amt in authorized_deductions.items():
                nk = name_key.upper()
                if nk == full_name or nk == last_name or nk in full_name or last_name in nk:
                    auth_amount = amt
                    matched_key = name_key
                    break
                if get_close_matches(nk, [full_name, last_name], n=1, cutoff=0.75):
                    auth_amount = amt
                    matched_key = name_key
                    break

            if auth_amount is not None:
                if abs(deductions - auth_amount) > TOLERANCE:
                    issues.append({
                        "text": (
                            f"Deduction ${deductions:.2f} does not match authorized amount "
                            f"${auth_amount:.2f} from document on file for '{matched_key}' "
                            f"— possible unauthorized deduction"
                        ),
                        "regulation": "Copeland Anti-Kickback Act; 29 CFR 3.5",
                        "severity": "VIOLATION",
                    })

        violations = [i for i in issues if i["severity"] == "VIOLATION"]
        warnings = [i for i in issues if i["severity"] == "WARNING"]

        if violations:
            row_result = "FAIL"
            results["passed"] = False
        elif warnings:
            row_result = "WARN"
        else:
            row_result = "PASS"

        reason_parts = [i["text"] for i in issues]
        reg_parts = list({i["regulation"] for i in issues})

        results["by_row"][row] = {
            "result": row_result,
            "reason": " | ".join(reason_parts),
            "regulation": "; ".join(reg_parts),
            "severity": "VIOLATION" if violations else ("WARNING" if warnings else ""),
        }

        results["checks"].append({
            "row": row,
            "result": row_result,
            "details": " | ".join(reason_parts) or "OK",
            "regulation": "; ".join(reg_parts),
        })

    return results
