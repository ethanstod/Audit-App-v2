"""
Fringe Benefit Compliance Audit
Davis-Bacon Act Sec. 1(b)(2); 29 CFR 5.5(a)(1)(ii)

Contractors must pay prevailing fringe benefits either:
(A) as cash in addition to base wages, OR
(B) through bona fide benefit plans (health, pension, vacation, etc.)

Total hourly compensation (base + fringe) must equal or exceed the
wage determination total package.
"""

from pay_audit import find_wage_row

TOLERANCE = 0.02


def audit_fringe_benefits(parsed_data, wage_table):
    """
    For each worker:
    1. Compute required fringe from wage determination (flat + pct-of-base)
    2. Compute worker's reported fringe (cash + plan contributions)
    3. Check total compensation >= wage determination total package
    4. Flag bona fide plan issues (plan amount reported but no plan name)

    Note: Excess base pay above the required base rate can offset fringe
    shortfall — total compensation is what matters, not base alone.

    Regulation: 29 CFR 5.5(a)(1)(ii); Davis-Bacon Act Sec. 1(b)(2)
    """

    workers = parsed_data.get("lines", [])
    results = {
        "audit_name": "fringe",
        "passed": True,
        "checks": [],
        "by_row": {},
    }

    if wage_table.empty:
        return results

    for worker in workers:
        row = worker.get("row_number")
        j_ra = worker.get("j_ra", "").upper()
        classification = worker.get("classification", "")
        st_rate = float(worker.get("st_rate", worker.get("rate", 0)))
        fringe_cash = float(worker.get("fringe_paid_cash", 0))
        fringe_plan_amount = float(worker.get("fringe_plan_amount", 0))
        fringe_plan_name = str(worker.get("fringe_plan_name", "")).strip()
        reported_fringe = fringe_cash + fringe_plan_amount
        issues = []

        wage_row = find_wage_row(classification, wage_table)

        if wage_row is None:
            # Cannot audit fringe without a wage determination match
            results["by_row"][row] = {
                "result": "WARN",
                "reason": f"No wage table match for '{classification}' — fringe check skipped",
                "regulation": "29 CFR 5.5(a)(1)(ii)",
                "severity": "WARNING",
            }
            results["checks"].append({
                "row": row,
                "result": "WARN",
                "details": f"No wage table match for '{classification}'",
                "regulation": "29 CFR 5.5(a)(1)(ii)",
            })
            continue

        journeyman_base = float(wage_row["BASE_RATE"])
        fringe_flat = float(wage_row.get("FRINGE_FLAT", 0))
        fringe_pct  = float(wage_row.get("FRINGE_PCT", 0))

        # Required fringe is always the full journeyman fringe amount.
        # Per 29 CFR 5.5(a)(4)(i), apprentices must receive the full fringe
        # listed on the wage determination (not a prorated amount).
        required_fringe = round(fringe_flat + (journeyman_base * fringe_pct), 2)

        if j_ra == "RA":
            # --- Apprentice fringe check ---
            # For apprentices: only verify that full fringe is paid.
            # Base rate compliance is handled by audit_apprentice_rates.
            if required_fringe > 0 and reported_fringe < required_fringe - TOLERANCE:
                shortfall = round(required_fringe - reported_fringe, 2)
                issues.append({
                    "text": (
                        f"Fringe ${reported_fringe:.2f}/hr < required ${required_fringe:.2f}/hr. "
                        f"Apprentices must receive full fringe per 29 CFR 5.5(a)(4)(i). "
                        f"Shortfall: ${shortfall:.2f}/hr"
                    ),
                    "regulation": "29 CFR 5.5(a)(4)(i); 29 CFR 5.5(a)(1)(ii)",
                    "severity": "VIOLATION",
                })
        else:
            # --- Journeyman total compensation check ---
            # Excess base pay above required base may offset a fringe shortfall.
            required_total = round(journeyman_base + required_fringe, 2)
            reported_total = round(st_rate + reported_fringe, 2)

            if required_fringe > 0 and reported_total < required_total - TOLERANCE:
                shortfall = round(required_total - reported_total, 2)
                issues.append({
                    "text": (
                        f"Total compensation ${reported_total:.2f}/hr "
                        f"(base ${st_rate:.2f} + fringe ${reported_fringe:.2f}) "
                        f"< required ${required_total:.2f}/hr "
                        f"(base ${journeyman_base:.2f} + fringe ${required_fringe:.2f}). "
                        f"Shortfall: ${shortfall:.2f}/hr"
                    ),
                    "regulation": "29 CFR 5.5(a)(1)(ii); Davis-Bacon Act Sec. 1(b)(2)",
                    "severity": "VIOLATION",
                })

        # Bona fide plan: plan amount reported but no plan name given
        if fringe_plan_amount > 0 and not fringe_plan_name:
            issues.append({
                "text": (
                    f"Fringe plan contribution of ${fringe_plan_amount:.2f}/hr reported "
                    f"but no plan name provided — plan name required for credit"
                ),
                "regulation": "29 CFR 5.5(a)(1)(ii)(B)",
                "severity": "WARNING",
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
