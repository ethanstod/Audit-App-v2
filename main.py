import os
import argparse

from pdf_parser import extract_wh347_data
from math_audit import audit_wh347_math
from cwhssa_audit import audit_cwhssa
from pay_audit import load_wage_table, audit_all_workers, audit_apprentice_rates, audit_deductions
from fringe_audit import audit_fringe_benefits
from classification_audit import audit_classifications
from header_audit import audit_header
from wh347_report import generate_wh347_html_report


def audit_wh347_form(pdf_path, wage_table_path="cleaned_rates.xlsx", output_path=None):
    """
    Runs a full DOL Davis-Bacon compliance audit on a WH-347 certified payroll form.
    Returns (report_data, output_path).
    """

    if not os.path.exists(pdf_path):
        print(f"❌ PDF file not found: {pdf_path}")
        return None, None

    print("[*] Parsing WH-347 PDF...")
    parsed_data = extract_wh347_data(pdf_path)
    print(f"    Workers detected: {parsed_data['totals']['workers']} "
          f"({parsed_data['totals']['journeymen']} J / "
          f"{parsed_data['totals']['apprentices']} RA)")

    header = parsed_data.get("header", {})
    if header.get("week_ending"):
        print(f"    Week Ending: {header['week_ending']}")
    if header.get("contractor_name"):
        print(f"    Contractor:  {header['contractor_name']}")
    if header.get("contract_number"):
        print(f"    Contract #:  {header['contract_number']}")

    print("\n[*] Running audit modules...")

    print("    [1/7] Header & Statement of Compliance...")
    header_results = audit_header(parsed_data)

    print("    [2/7] Mathematical validation...")
    math_results = audit_wh347_math(parsed_data)

    print("    [3/7] CWHSSA overtime compliance...")
    cwhssa_results = audit_cwhssa(parsed_data)

    print("    [4/7] Loading wage table...")
    wage_table = load_wage_table(wage_table_path)

    print("    [5/7] Prevailing wage / classification checks...")
    pay_results = audit_all_workers(parsed_data, wage_table)
    class_results = audit_classifications(parsed_data, wage_table)

    print("    [6/7] Fringe benefit compliance...")
    fringe_results = audit_fringe_benefits(parsed_data, wage_table)

    print("    [7/7] Apprentice rates, ratios & deductions...")
    apprentice_results = audit_apprentice_rates(parsed_data, wage_table)
    deduction_results = audit_deductions(parsed_data)

    # Overall pass = every module passed
    overall_pass = all([
        header_results.get("passed", True),
        math_results.get("passed", True),
        cwhssa_results.get("passed", True),
        pay_results.get("passed", True),
        fringe_results.get("passed", True),
        apprentice_results.get("passed", True),
        deduction_results.get("passed", True),
        class_results.get("passed", True),
    ])

    report_data = {
        "parsed_data":   parsed_data,
        "header_audit":  header_results,
        "math":          math_results,
        "cwhssa":        cwhssa_results,
        "pay":           pay_results,
        "fringe":        fringe_results,
        "apprentice":    apprentice_results,
        "deductions":    deduction_results,
        "classification": class_results,
        "passed":        overall_pass,
    }

    print("\n[*] Generating HTML report...")
    report_path = generate_wh347_html_report(report_data, output_path)

    # Print summary
    print("\n" + "=" * 50)
    print("  WH-347 DAVIS-BACON COMPLIANCE AUDIT COMPLETE")
    print("=" * 50)

    print(f"  Overall Status : {'PASS' if overall_pass else 'FAIL'}")
    print(f"  Report saved to: {report_path}")
    print()

    modules = [
        ("Header / Compliance",  header_results),
        ("Math Validation",      math_results),
        ("CWHSSA Overtime",      cwhssa_results),
        ("Prevailing Wage",      pay_results),
        ("Fringe Benefits",      fringe_results),
        ("Apprentice/Ratio",     apprentice_results),
        ("Deductions",           deduction_results),
        ("Classification",       class_results),
    ]
    for label, res in modules:
        passed = res.get("passed", True)
        symbol = "[PASS]" if passed else "[FAIL]"
        print(f"  {symbol} {label}")

    ld = cwhssa_results.get("total_liquidated_damages_estimate", 0.0)
    if ld > 0:
        print(f"\n  [!] CWHSSA liquidated damages exposure: ${ld:.2f}/day")

    print("=" * 50 + "\n")

    return report_data, report_path


def main():
    parser = argparse.ArgumentParser(
        description="WH-347 Davis-Bacon Federal Compliance Audit Engine",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python main.py payroll.pdf
  python main.py payroll.pdf --wages WA20250002_rates.xlsx
  python main.py payroll.pdf --wages rates.xlsx --output audit_report.html
        """
    )
    parser.add_argument("pdf", nargs="?", help="Path to WH-347 PDF file")
    parser.add_argument("--wages", default="cleaned_rates.xlsx",
                        help="Path to prevailing wage rate Excel file (default: cleaned_rates.xlsx)")
    parser.add_argument("--output", default=None,
                        help="Output HTML report path (default: report_wh347.html)")
    args = parser.parse_args()

    print("=" * 50)
    print("  WH-347 Davis-Bacon Compliance Audit Engine")
    print("  U.S. Department of Labor - DBRA Compliance")
    print("=" * 50 + "\n")

    pdf_file = args.pdf
    if not pdf_file:
        pdf_file = input("Enter path to WH-347 PDF: ").strip()

    if not pdf_file:
        print("❌ No file entered.")
        return

    audit_wh347_form(
        pdf_path=pdf_file,
        wage_table_path=args.wages,
        output_path=args.output,
    )


if __name__ == "__main__":
    main()
