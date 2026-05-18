"""
Contract Work Hours and Safety Standards Act (CWHSSA) Audit
40 U.S.C. 3702 — Overtime pay requirements for federal contracts.

Liquidated damages: $31 per calendar day per affected worker (2024 rate).
"""

CWHSSA_LIQUIDATED_DAMAGES_PER_DAY = 31.00
OVERTIME_THRESHOLD = 40.0
TOLERANCE = 0.02


def audit_cwhssa(parsed_data):
    """
    Checks:
    1. Workers with total_hours > 40 must have OT hours >= (total_hours - 40).
       Catches both "no OT at all" and partial under-reporting.
    2. OT rate must be >= 1.5x ST rate.
    3. Estimates liquidated damages and back-wages where applicable.

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
        back_wages = 0.0

        total_hrs = float(worker.get("total_hours", 0))
        ot_hrs    = float(worker.get("ot_hours", 0))
        st_rate   = float(worker.get("st_rate", 0))
        ot_rate   = float(worker.get("ot_rate", 0))

        # Check 1: All hours over 40 must be compensated at OT rate.
        # Catches both zero-OT and partial under-reporting in one check.
        if total_hrs > OVERTIME_THRESHOLD:
            required_ot_hrs = round(total_hrs - OVERTIME_THRESHOLD, 2)
            missing_ot_hrs  = round(required_ot_hrs - ot_hrs, 2)

            if missing_ot_hrs > TOLERANCE:
                est_days = min(5, max(1, round(missing_ot_hrs)))
                ld_amount = est_days * CWHSSA_LIQUIDATED_DAMAGES_PER_DAY
                # Back-wages: only the OT premium (0.5×) since the base was paid at ST
                ot_back_wages = round(missing_ot_hrs * 0.5 * st_rate, 2) if st_rate > 0 else 0.0
                back_wages += ot_back_wages

                if ot_hrs == 0.0:
                    text = (
                        f"Worker has {total_hrs:.1f} total hours but no OT hours reported — "
                        f"{required_ot_hrs:.1f} hrs must be paid at 1.5× rate. "
                        f"OT premium back-wages est.: ${ot_back_wages:.2f}. "
                        f"LD exposure: {est_days}d × ${CWHSSA_LIQUIDATED_DAMAGES_PER_DAY:.0f} "
                        f"= ${ld_amount:.0f}."
                    )
                else:
                    text = (
                        f"Only {ot_hrs:.1f} OT hrs reported but {required_ot_hrs:.1f} are required "
                        f"({total_hrs:.1f} total hrs − 40 threshold). "
                        f"{missing_ot_hrs:.1f} hrs paid at ST instead of OT rate. "
                        f"OT premium back-wages est.: ${ot_back_wages:.2f}. "
                        f"LD exposure: {est_days}d × ${CWHSSA_LIQUIDATED_DAMAGES_PER_DAY:.0f} "
                        f"= ${ld_amount:.0f}."
                    )

                issues.append({
                    "text": text,
                    "regulation": "40 U.S.C. 3702; 29 CFR 5.8",
                    "severity": "VIOLATION",
                    "liquidated_damages": ld_amount,
                })

        # Check 2: OT rate must be >= 1.5x ST rate
        if ot_hrs > 0 and st_rate > 0:
            required_ot = round(st_rate * 1.5, 2)
            if ot_rate < required_ot - TOLERANCE:
                rate_shortfall = round(required_ot - ot_rate, 2)
                ot_rate_back_wages = round(ot_hrs * rate_shortfall, 2)
                back_wages += ot_rate_back_wages
                issues.append({
                    "text": (
                        f"OT rate ${ot_rate:.2f} < required ${required_ot:.2f} "
                        f"(1.5× ST ${st_rate:.2f}). "
                        f"Rate shortfall back-wages est.: ${ot_rate_back_wages:.2f}."
                    ),
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
            "back_wages_estimate": round(back_wages, 2),
        }

        results["checks"].append({
            "row": row,
            "worker": f"{worker.get('first_name')} {worker.get('last_name')}",
            "result": row_result,
            "details": " | ".join(reason_parts) or "OK",
            "regulation": "40 U.S.C. 3702; 29 CFR 5.8" if issues else "",
        })

    return results
