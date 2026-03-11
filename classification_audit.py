"""
Worker Classification Audit
29 CFR 5.5(a)(1)(i) — Workers must be classified and paid at the rate
applicable to the work they actually perform.

Misclassification (e.g., classifying a Journeyman Electrician as a
general Laborer to pay a lower rate) is a primary Davis-Bacon violation.
"""

from difflib import get_close_matches

FUZZY_CUTOFF = 0.75


def audit_classifications(parsed_data, wage_table):
    """
    For each worker:
    1. Checks that the reported classification exists in the wage determination.
    2. If fuzzy-matched (not exact), flags as WARN for manual review.
    3. If no match found (score < 0.75), flags as FAIL.

    Note: This audit cannot verify that workers were correctly classified
    for the work they actually performed — that requires a field investigation.
    This audit verifies that the reported classification is a valid wage
    determination classification.

    Regulation: 29 CFR 5.5(a)(1)(i)
    """

    workers = parsed_data.get("lines", [])
    results = {
        "audit_name": "classification",
        "passed": True,
        "checks": [],
        "by_row": {},
    }

    if wage_table.empty:
        return results

    wage_classes = wage_table["CLASSIFICATION"].tolist()

    for worker in workers:
        row = worker.get("row_number")
        classification = str(worker.get("classification", "")).upper().strip()
        issues = []
        fuzzy_match = None

        if not classification or classification in ("UNKNOWN", ""):
            results["by_row"][row] = {
                "result": "WARN",
                "reason": "Classification not extracted from PDF — verify manually",
                "regulation": "29 CFR 5.5(a)(1)(i)",
                "severity": "WARNING",
            }
            results["checks"].append({
                "row": row,
                "result": "WARN",
                "details": "Classification missing from parsed data",
                "regulation": "29 CFR 5.5(a)(1)(i)",
            })
            continue

        # Exact match
        exact_matches = [c for c in wage_classes if c == classification]
        if exact_matches:
            row_result = "PASS"
            reason = ""
        else:
            # Fuzzy match
            close = get_close_matches(classification, wage_classes, n=1, cutoff=FUZZY_CUTOFF)
            if close:
                fuzzy_match = close[0]
                row_result = "WARN"
                reason = (
                    f"Classification '{classification}' not exact match in wage determination. "
                    f"Closest match: '{fuzzy_match}' — verify this is the correct classification."
                )
            else:
                row_result = "FAIL"
                reason = (
                    f"Classification '{classification}' has no match in wage determination. "
                    f"Worker may be misclassified or using non-standard trade name."
                )
                results["passed"] = False

        results["by_row"][row] = {
            "result": row_result,
            "reason": reason,
            "regulation": "29 CFR 5.5(a)(1)(i)",
            "severity": "VIOLATION" if row_result == "FAIL" else ("WARNING" if row_result == "WARN" else ""),
            "fuzzy_match": fuzzy_match,
        }

        results["checks"].append({
            "row": row,
            "result": row_result,
            "details": reason or f"Classification '{classification}' verified",
            "regulation": "29 CFR 5.5(a)(1)(i)",
        })

    return results
