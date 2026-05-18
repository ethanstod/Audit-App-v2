import os
import argparse

from pdf_parser import extract_wh347_data
from math_audit import audit_wh347_math, audit_payroll_sanity
from cwhssa_audit import audit_cwhssa
from pay_audit import load_wage_table, audit_all_workers, audit_apprentice_rates, audit_deductions
from fringe_audit import audit_fringe_benefits
from classification_audit import audit_classifications
from header_audit import audit_header
from wh347_report import generate_wh347_html_report
from document_loader import resolve_docs, list_cprs


def audit_wh347_form(
    pdf_path,
    wage_table_path="cleaned_rates.xlsx",
    output_path=None,
    docs_root=None,
    data_root=None,
):
    """
    Runs a full DOL Davis-Bacon compliance audit on a WH-347 certified payroll form.
    Returns (report_data, output_path).
    """

    if not os.path.exists(pdf_path):
        print(f"[!] PDF file not found: {pdf_path}")
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

    # --- Auto-discover supporting documents ---
    if docs_root or data_root:
        docs = resolve_docs(parsed_data.get("header", {}), docs_root=docs_root, data_root=data_root)
        if docs["wage_schedule"]:
            print(f"    Wage schedule: {os.path.basename(docs['wage_schedule'])}")
            wage_table_path = docs["wage_schedule"]
        else:
            print(f"    Wage schedule: using default ({os.path.basename(wage_table_path)})")

        if docs["apprentice_certs"]:
            print(f"    Apprentice certs: {len(docs['apprentice_certs'])} found — parsing...")
            _load_and_match_certs(docs["apprentice_certs"], parsed_data)
        else:
            print("    Apprentice certs: none found in certs directory")

        if docs["fringe_plans"]:
            print(f"    Fringe plans: {len(docs['fringe_plans'])} found")

    print("\n[*] Running audit modules...")

    print("    [1/8] Header & Statement of Compliance...")
    header_results = audit_header(parsed_data)

    print("    [2/8] Payroll sanity checks...")
    sanity_results = audit_payroll_sanity(parsed_data)

    print("    [3/8] Mathematical validation...")
    math_results = audit_wh347_math(parsed_data)

    print("    [4/8] CWHSSA overtime compliance...")
    cwhssa_results = audit_cwhssa(parsed_data)

    print("    [5/8] Loading wage table...")
    wage_table = load_wage_table(wage_table_path)

    print("    [6/8] Prevailing wage / classification checks...")
    pay_results = audit_all_workers(parsed_data, wage_table)
    class_results = audit_classifications(parsed_data, wage_table)

    print("    [7/8] Fringe benefit compliance...")
    fringe_results = audit_fringe_benefits(parsed_data, wage_table)

    print("    [8/8] Apprentice rates, ratios & deductions...")
    apprentice_results = audit_apprentice_rates(parsed_data, wage_table)
    deduction_results = audit_deductions(parsed_data)

    # Overall pass = every module passed
    overall_pass = all([
        header_results.get("passed", True),
        sanity_results.get("passed", True),
        math_results.get("passed", True),
        cwhssa_results.get("passed", True),
        pay_results.get("passed", True),
        fringe_results.get("passed", True),
        apprentice_results.get("passed", True),
        deduction_results.get("passed", True),
        class_results.get("passed", True),
    ])

    report_data = {
        "parsed_data":    parsed_data,
        "header_audit":   header_results,
        "sanity":         sanity_results,
        "math":           math_results,
        "cwhssa":         cwhssa_results,
        "pay":            pay_results,
        "fringe":         fringe_results,
        "apprentice":     apprentice_results,
        "deductions":     deduction_results,
        "classification": class_results,
        "passed":         overall_pass,
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
        ("Payroll Sanity",       sanity_results),
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


def _load_and_match_certs(cert_paths: list, parsed_data: dict) -> None:
    """Load apprentice certs (with JSON cache) and match to RA workers."""
    try:
        from cert_loader import load_all_certs, match_certs_to_workers
        certs = load_all_certs(cert_paths)
        if certs:
            match_certs_to_workers(parsed_data.get("lines", []), certs)
            matched = sum(
                1 for w in parsed_data.get("lines", [])
                if w.get("worker_type", "").upper() == "RA" and w.get("apprentice_cert")
            )
            print(f"    Matched {matched} RA worker(s) to certs")
    except ImportError:
        pass
    except Exception as exc:
        print(f"    [!] Cert loading error: {exc}")


def run_batch(cprs_dir: str, wage_table_path: str, docs_root: str | None, data_root: str | None) -> None:
    """Audit all CPR PDFs in cprs_dir and print a summary table."""
    cprs = list_cprs(cprs_dir)
    if not cprs:
        print(f"[!] No CPR PDFs found in: {cprs_dir}")
        return

    print(f"[*] Batch mode: {len(cprs)} CPR(s) found in {cprs_dir}\n")

    summary = []
    for pdf_path in cprs:
        name = os.path.basename(pdf_path)
        stem = os.path.splitext(pdf_path)[0]
        out_path = stem + "_audit.html"
        print(f"--- Auditing: {name} ---")
        report_data, report_path = audit_wh347_form(
            pdf_path,
            wage_table_path=wage_table_path,
            output_path=out_path,
            docs_root=docs_root,
            data_root=data_root,
        )
        if report_data:
            summary.append((name, report_data.get("passed", False), report_path))

    print("\n" + "=" * 60)
    print("  BATCH AUDIT SUMMARY")
    print("=" * 60)
    pass_count = sum(1 for _, p, _ in summary if p)
    print(f"  {pass_count}/{len(summary)} payrolls PASSED\n")
    for name, passed, rpath in summary:
        sym = "[PASS]" if passed else "[FAIL]"
        print(f"  {sym}  {name}")
        print(f"         {rpath}")
    print("=" * 60 + "\n")


def main():
    parser = argparse.ArgumentParser(
        description="WH-347 Davis-Bacon Federal Compliance Audit Engine",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python main.py payroll.pdf
  python main.py payroll.pdf --wages WA20250002_rates.xlsx
  python main.py payroll.pdf --wages rates.xlsx --output audit_report.html
  python main.py payroll.pdf --docs-dir ./wh347_auditor
  python main.py --batch --docs-dir ./wh347_auditor
        """
    )
    parser.add_argument("pdf", nargs="?", help="Path to WH-347 PDF file")
    parser.add_argument("--wages", default="cleaned_rates.xlsx",
                        help="Path to prevailing wage rate Excel file (default: cleaned_rates.xlsx)")
    parser.add_argument("--output", default=None,
                        help="Output HTML report path (default: report_wh347.html)")
    parser.add_argument(
        "--docs-dir",
        default=None,
        metavar="DIR",
        help=(
            "Root directory containing documents/ and data/ sub-folders "
            "(CPRs, apprentice certs, fringe plans, wage schedules). "
            "When set, wage schedules and certs are auto-discovered."
        ),
    )
    parser.add_argument(
        "--batch",
        action="store_true",
        help=(
            "Audit all CPR PDFs found in <docs-dir>/documents/cprs/. "
            "Requires --docs-dir."
        ),
    )
    args = parser.parse_args()

    print("=" * 50)
    print("  WH-347 Davis-Bacon Compliance Audit Engine")
    print("  U.S. Department of Labor - DBRA Compliance")
    print("=" * 50 + "\n")

    docs_root = args.docs_dir
    data_root = args.docs_dir

    if args.batch:
        if not docs_root:
            print("[!] --batch requires --docs-dir to be set.")
            return
        cprs_dir = os.path.join(docs_root, "documents", "cprs")
        run_batch(cprs_dir, args.wages, docs_root, data_root)
        return

    pdf_file = args.pdf
    if not pdf_file:
        pdf_file = input("Enter path to WH-347 PDF: ").strip()

    if not pdf_file:
        print("[!] No file entered.")
        return

    audit_wh347_form(
        pdf_path=pdf_file,
        wage_table_path=args.wages,
        output_path=args.output,
        docs_root=docs_root,
        data_root=data_root,
    )


if __name__ == "__main__":
    main()
