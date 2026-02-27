def audit_wh347_math(parsed_data):
    """
    Performs mathematical validation on parsed WH-347 worker rows.

    Checks:
    - ST + OT + DT == Total Hours
    - Gross - Deductions == Net
    """

    workers = parsed_data.get("lines", [])
    results = {
        "passed": True,
        "checks": [],
        "by_row": {}
    }

    for worker in workers:
        row = worker.get("row_number")
        issues = []

        st = float(worker.get("st_hours", 0))
        ot = float(worker.get("ot_hours", 0))
        dt = float(worker.get("dt_hours", 0))
        total = float(worker.get("total_hours", 0))

        gross = float(worker.get("gross", 0))
        deductions = float(worker.get("deductions", 0))
        net = float(worker.get("net", 0))

        # Hours validation
        if round(st + ot + dt, 2) != round(total, 2):
            issues.append(
                f"Hours mismatch ({st + ot + dt:.2f} != {total:.2f})"
            )

        # Net validation
        if round(gross - deductions, 2) != round(net, 2):
            issues.append(
                f"Net mismatch ({gross - deductions:.2f} != {net:.2f})"
            )

        if issues:
            results["passed"] = False
            results["by_row"][row] = {
                "result": "FAIL",
                "reason": "; ".join(issues)
            }
        else:
            results["by_row"][row] = {
                "result": "PASS",
                "reason": ""
            }

        results["checks"].append({
            "row": row,
            "worker": f"{worker.get('first_name')} {worker.get('last_name')}",
            "result": results["by_row"][row]["result"],
            "details": results["by_row"][row]["reason"] or "OK"
        })

    return results
