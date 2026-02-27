import pandas as pd
import os
from difflib import get_close_matches


def load_wage_table(path):
    """
    Loads wage rate Excel file.
    Expects cleaned_rates.xlsx with a classification column and rate column.
    """

    if not os.path.exists(path):
        print("⚠️ Wage table not found.")
        return pd.DataFrame()

    try:
        df = pd.read_excel(path)
    except Exception as e:
        print("❌ Failed to load wage table:", e)
        return pd.DataFrame()

    # Normalize columns
    df.columns = [c.strip().upper() for c in df.columns]

    # Try to detect classification + rate columns
    class_col = None
    rate_col = None

    for col in df.columns:
        if "CLASS" in col:
            class_col = col
        if "RATE" in col:
            rate_col = col

    if not class_col or not rate_col:
        print("⚠️ Could not detect classification or rate column.")
        return pd.DataFrame()

    df["CLASSIFICATION"] = df[class_col].astype(str).str.upper().str.strip()
    df["RATE"] = pd.to_numeric(df[rate_col], errors="coerce")

    df = df.dropna(subset=["RATE"])

    return df[["CLASSIFICATION", "RATE"]]


def audit_all_workers(parsed_data, wage_table):
    """
    Validates that reported base rate >= required rate.
    """

    workers = parsed_data.get("lines", [])
    results = {
        "passed": True,
        "checks": [],
        "by_row": {}
    }

    if wage_table.empty:
        print("⚠️ No wage table loaded — skipping pay audit.")
        return {
            "passed": True,
            "checks": [],
            "by_row": {}
        }

    wage_classes = wage_table["CLASSIFICATION"].tolist()

    for worker in workers:
        row = worker.get("row_number")
        classification = worker.get("classification", "").upper()
        reported_rate = float(worker.get("rate", 0))

        match = get_close_matches(classification, wage_classes, n=1, cutoff=0.6)

        if not match:
            results["by_row"][row] = {
                "result": "WARN",
                "reason": f"No wage match for '{classification}'"
            }
            results["checks"].append({
                "row": row,
                "result": "WARN",
                "details": "No classification match"
            })
            continue

        required_rate = float(
            wage_table.loc[
                wage_table["CLASSIFICATION"] == match[0], "RATE"
            ].iloc[0]
        )

        if reported_rate < required_rate:
            results["passed"] = False
            results["by_row"][row] = {
                "result": "FAIL",
                "reason": f"Rate ${reported_rate} below required ${required_rate}"
            }
        else:
            results["by_row"][row] = {
                "result": "PASS",
                "reason": ""
            }

        results["checks"].append({
            "row": row,
            "result": results["by_row"][row]["result"],
            "details": results["by_row"][row]["reason"] or "OK"
        })

    return results
