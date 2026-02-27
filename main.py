from pdf_parser import extract_wh347_data
from math_audit import audit_wh347_math
from pay_audit import load_wage_table, audit_all_workers
from wh347_report import generate_wh347_html_report
import os


def audit_wh347_form(pdf_path, wage_table_path="cleaned_rates.xlsx"):
    if not os.path.exists(pdf_path):
        print("❌ PDF file not found.")
        return

    print("📄 Parsing WH-347 PDF...")
    parsed_data = extract_wh347_data(pdf_path)

    print(f"   → Workers detected: {parsed_data['totals']['workers']}")

    print("🧮 Running math audit...")
    math_results = audit_wh347_math(parsed_data)

    print("💰 Loading wage rate table...")
    wage_table = load_wage_table(wage_table_path)

    print("🧾 Running pay audit...")
    pay_results = audit_all_workers(parsed_data, wage_table)

    overall_pass = math_results["passed"] and pay_results["passed"]

    report_data = {
        "parsed_data": parsed_data,
        "math": math_results,
        "pay": pay_results,
        "passed": overall_pass,
    }

    print("📝 Generating HTML report...")
    output_path = generate_wh347_html_report(report_data)

    print("\n==============================")
    print("AUDIT COMPLETE")
    print("==============================")
    print(f"Overall Status: {'PASS' if overall_pass else 'FAIL'}")
    print(f"Report saved to: {output_path}")
    print("==============================\n")


if __name__ == "__main__":
    print("WH-347 Federal Audit Engine\n")

    pdf_file = input("Enter path to WH-347 PDF: ").strip()

    if not pdf_file:
        print("❌ No file entered.")
    else:
        audit_wh347_form(pdf_file)
