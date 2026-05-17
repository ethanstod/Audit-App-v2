"""
Contract Work Hours and Safety Standards Act (CWHSSA) Audit
40 U.S.C. 3702 — Overtime pay requirements for federal contracts.

Liquidated damages: $31 per calendar day per affected worker (2024 rate).
"""

CWHSSA_LIQUIDATED_DAMAGES_PER_DAY = 31.00
OVERTIME_THRESHOLD = 40.0


def audit_cwhssa(parsed_data):
    """
    Checks:
    1. Workers with total_hours > 40 must have OT hours reported.
    2. OT rate must be >= 1.5x ST rate.
    3. Estimates liquidated damages exposure where applicable.

    Regulation: 40 U.S.C. 3702; 29 CFR 5.8
    """

    workers = parsed_data.get("lines", [])
    results = {
        "audit_name": "cwhssa",
        "passed": True,
        "checks": [],
        "by_row": {},
        "total_liquidated_damages_estimate": 0.0,
    }

    for worker in workers:
        row = worker.get("row_number")
        issues = []

        total_hrs = float(worker.get("total_hours", 0))
        ot_hrs = float(worker.get("ot_hours", 0))
        st_rate = float(worker.get("st_rate", 0))
        ot_rate = float(worker.get("ot_rate", 0))

        # Check 1: OT hours required when total > 40
        if total_hrs > OVERTIME_THRESHOLD and ot_hrs == 0.0:
            overtime_hours_due = round(total_hrs - OVERTIME_THRESHOLD, 2)
            # Estimate calendar days the violation occurred: assume OT was spread
            # across the workweek (1 OT hour/day minimum → OT_hrs days affected).
            # Use the lesser of OT hours and 5 (max workweek days) for the estimate.
            est_days = min(5, max(1, round(overtime_hours_due)))
            issues.append({
                "text": (
                    f"Worker has {total_hrs:.1f} total hours but no OT hours reported — "
                    f"{overtime_hours_due:.1f} hrs should be paid at OT (1.5×) rate. "
                    f"Est. LD exposure: {est_days} day(s) × ${CWHSSA_LIQUIDATED_DAMAGES_PER_DAY:.0f} "
                    f"= ${est_days * CWHSSA_LIQUIDATED_DAMAGES_PER_DAY:.0f}."
                ),
                "regulation": "40 U.S.C. 3702; 29 CFR 5.8",
                "severity": "VIOLATION",
                "liquidated_damages": est_days * CWHSSA_LIQUIDATED_DAMAGES_PER_DAY,
            })

        # Check 2: OT rate must be >= 1.5x ST rate
        if ot_hrs > 0 and st_rate > 0:
            required_ot = round(st_rate * 1.5, 2)
            if ot_rate < required_ot - 0.02:
                issues.append({
                    "text": f"OT rate ${ot_rate:.2f} < required ${required_ot:.2f} (1.5× ST rate ${st_rate:.2f})",
                    "regulation": "40 U.S.C. 3702; 29 CFR 5.8",
                    "severity": "VIOLATION",
                    "liquidated_damages": CWHSSA_LIQUIDATED_DAMAGES_PER_DAY,
                })

        violations = [i for i in issues if i["severity"] == "VIOLATION"]

        if violations:
            row_result = "FAIL"
            results["passed"] = False
            damage_estimate = sum(i.get("liquidated_damages", CWHSSA_LIQUIDATED_DAMAGES_PER_DAY)
                                  for i in violations)
            results["total_liquidated_damages_estimate"] += damage_estimate
        else:
            row_result = "PASS"

        reason_parts = [i["text"] for i in issues]

        results["by_row"][row] = {
            "result": row_result,
            "reason": " | ".join(reason_parts),
            "regulation": "40 U.S.C. 3702; 29 CFR 5.8" if issues else "",
            "severity": "VIOLATION" if violations else "",
        }

        results["checks"].append({
            "row": row,
            "worker": f"{worker.get('first_name')} {worker.get('last_name')}",
            "result": row_result,
            "details": " | ".join(reason_parts) or "OK",
            "regulation": "40 U.S.C. 3702; 29 CFR 5.8" if issues else "",
        })

    return results
