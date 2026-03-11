TOLERANCE = 0.02  # dollar rounding tolerance


def audit_wh347_math(parsed_data):
    """
    Mathematical validation on WH-347 worker rows.

    Checks:
    1. ST + OT + DT hours == Total Hours
    2. Gross - Deductions == Net
    3. (ST hrs × ST rate) + (OT hrs × OT rate) + (DT hrs × DT rate) == Gross
    4. OT rate >= 1.5 × ST rate (when OT hours exist)
    5. Net pay is non-negative (Copeland Act)

    Regulation references embedded in each finding.
    """

    workers = parsed_data.get("lines", [])
    results = {
        "audit_name": "math",
        "passed": True,
        "checks": [],
        "by_row": {}
    }

    for worker in workers:
        row = worker.get("row_number")
        issues = []

        st_hrs = float(worker.get("st_hours", 0))
        ot_hrs = float(worker.get("ot_hours", 0))
        dt_hrs = float(worker.get("dt_hours", 0))
        total_hrs = float(worker.get("total_hours", 0))

        st_rate = float(worker.get("st_rate", 0))
        ot_rate = float(worker.get("ot_rate", 0))
        dt_rate = float(worker.get("dt_rate", 0))

        st_gross = float(worker.get("st_gross", 0))
        ot_gross = float(worker.get("ot_gross", 0))
        dt_gross = float(worker.get("dt_gross", 0))
        gross = float(worker.get("gross", 0))
        deductions = float(worker.get("deductions", 0))
        net = float(worker.get("net", 0))

        # --- Check 1: Hours arithmetic ---
        computed_hours = round(st_hrs + ot_hrs + dt_hrs, 2)
        if abs(computed_hours - round(total_hrs, 2)) > TOLERANCE:
            issues.append({
                "text": f"Hours mismatch: ST({st_hrs})+OT({ot_hrs})+DT({dt_hrs})"
                        f"={computed_hours} ≠ Total({total_hrs})",
                "regulation": "29 CFR 5.5(a)(1)(i)",
                "severity": "VIOLATION",
            })

        # --- Check 2: Net pay arithmetic ---
        computed_net = round(gross - deductions, 2)
        if abs(computed_net - round(net, 2)) > TOLERANCE:
            issues.append({
                "text": f"Net mismatch: Gross({gross:.2f})-Deductions({deductions:.2f})"
                        f"={computed_net:.2f} ≠ Net({net:.2f})",
                "regulation": "29 CFR 5.5(a)(1)(i)",
                "severity": "VIOLATION",
            })

        # --- Check 3: Gross pay component check ---
        # Only run if we have per-type data (not the single-rate fallback collapse)
        all_same_rate = (ot_rate == round(st_rate * 1.5, 2) and
                         dt_rate == round(st_rate * 2.0, 2) and
                         ot_gross == 0.0 and dt_gross == 0.0)

        if not all_same_rate or (ot_hrs == 0.0 and dt_hrs == 0.0):
            expected_st_gross = round(st_hrs * st_rate, 2)
            expected_ot_gross = round(ot_hrs * ot_rate, 2)
            expected_dt_gross = round(dt_hrs * dt_rate, 2)
            expected_gross = round(expected_st_gross + expected_ot_gross + expected_dt_gross, 2)

            if abs(expected_gross - round(gross, 2)) > TOLERANCE:
                issues.append({
                    "text": f"Gross pay mismatch: computed ${expected_gross:.2f} "
                            f"(ST:{st_hrs}×${st_rate} + OT:{ot_hrs}×${ot_rate} + DT:{dt_hrs}×${dt_rate}) "
                            f"≠ reported ${gross:.2f}",
                    "regulation": "29 CFR 5.5(a)(1)(i)",
                    "severity": "VIOLATION",
                })

        # --- Check 4: OT rate multiplier ---
        if ot_hrs > 0 and st_rate > 0:
            required_ot_rate = round(st_rate * 1.5, 2)
            if ot_rate < required_ot_rate - TOLERANCE:
                issues.append({
                    "text": f"OT rate ${ot_rate:.2f} is below 1.5× ST rate "
                            f"(required ≥ ${required_ot_rate:.2f})",
                    "regulation": "CWHSSA, 40 U.S.C. 3702; 29 CFR 5.8",
                    "severity": "VIOLATION",
                })

        if dt_hrs > 0 and st_rate > 0:
            expected_dt_rate = round(st_rate * 2.0, 2)
            if dt_rate < expected_dt_rate - TOLERANCE:
                issues.append({
                    "text": f"DT rate ${dt_rate:.2f} appears below 2.0× ST rate "
                            f"(${expected_dt_rate:.2f}) — verify CBA",
                    "regulation": "Collective Bargaining Agreement / Local Wage Det.",
                    "severity": "WARNING",
                })

        # --- Check 5: Net pay non-negative (Copeland Act) ---
        if net < 0.0:
            issues.append({
                "text": f"Net pay is negative (${net:.2f}) — possible kickback violation",
                "regulation": "Copeland Anti-Kickback Act; 29 CFR 3.1",
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
            "worker": f"{worker.get('first_name')} {worker.get('last_name')}",
            "result": row_result,
            "details": " | ".join(reason_parts) or "OK",
            "regulation": "; ".join(reg_parts),
        })

    return results
