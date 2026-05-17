"""
Generate a synthetic WH-347 payroll PDF for testing the audit engine.

Workers and intentional violations:
  Row 1  MARTINEZ, Carlos  — CARPENTER       J  — PASS (correct rate + OT)
  Row 2  JOHNSON, Bob      — LABORER         J  — FAIL: underpaid ($34.00 vs $36.50)
  Row 3  CHEN, Wei         — IRONWORKER      RA — PASS: apprentice period-2 rate OK
  Row 4  TORRES, Maria     — OPERATOR        J  — FAIL: 50 hrs all ST (CWHSSA OT violation)
  Row 5  SMITH, David      — ELECTRICIAN     J  — FAIL: fringe $0 (required ~$24.47/hr)
"""

from reportlab.lib import colors
from reportlab.lib.pagesizes import landscape, letter
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle


# ---------------------------------------------------------------------------
# Payroll data
# ---------------------------------------------------------------------------
# Columns match pdf_parser.py strategy-3 layout (20-col pdfplumber path):
#   [0]row  [1]last  [2]first  [3]mi  [4]id  [5]j_ra  [6]class
#   [7]st_h [8]st_r  [9]st_g  [10]ot_h [11]ot_r [12]ot_g
#   [13]dt_h [14]dt_r [15]dt_g [16]tot_h [17]gross [18]ded [19]net [20]fringe

workers = [
    # Row 1: MARTINEZ, Carlos — CARPENTER J — correct, 40 ST + 5 OT
    {
        "row": 1, "last": "MARTINEZ", "first": "CARLOS", "mi": "R",
        "id": "E-1001", "j_ra": "J", "cls": "CARPENTER",
        "st_h": 40.0, "st_r": 44.50,
        "ot_h":  5.0, "ot_r": 66.75,
        "dt_h":  0.0, "dt_r":  0.00,
        "fringe": 15.85,
    },
    # Row 2: JOHNSON, Bob — LABORER J — FAIL: rate $34.00 (prevailing $36.50)
    {
        "row": 2, "last": "JOHNSON", "first": "BOB", "mi": "K",
        "id": "E-1002", "j_ra": "J", "cls": "LABORER",
        "st_h": 40.0, "st_r": 34.00,   # <-- underpaid
        "ot_h":  0.0, "ot_r":  0.00,
        "dt_h":  0.0, "dt_r":  0.00,
        "fringe": 13.25,
    },
    # Row 3: CHEN, Wei — IRONWORKER RA period-2 — PASS: 65% of $54.80 = $35.62
    {
        "row": 3, "last": "CHEN", "first": "WEI", "mi": "L",
        "id": "E-1003", "j_ra": "RA", "cls": "IRONWORKER",
        "st_h": 40.0, "st_r": 35.62,
        "ot_h":  0.0, "ot_r":  0.00,
        "dt_h":  0.0, "dt_r":  0.00,
        "fringe": 17.42,
    },
    # Row 4: TORRES, Maria — OPERATOR J — FAIL: 50 hrs all ST, no OT (CWHSSA)
    {
        "row": 4, "last": "TORRES", "first": "MARIA", "mi": "E",
        "id": "E-1004", "j_ra": "J", "cls": "OPERATOR",
        "st_h": 50.0, "st_r": 58.30,   # <-- 50 ST, no OT declared
        "ot_h":  0.0, "ot_r":  0.00,
        "dt_h":  0.0, "dt_r":  0.00,
        "fringe": 19.15,
    },
    # Row 5: SMITH, David — ELECTRICIAN J — FAIL: fringe $0 (required ~$24.47/hr)
    {
        "row": 5, "last": "SMITH", "first": "DAVID", "mi": "A",
        "id": "E-1005", "j_ra": "J", "cls": "ELECTRICIAN",
        "st_h": 40.0, "st_r": 57.45,
        "ot_h":  0.0, "ot_r":  0.00,
        "dt_h":  0.0, "dt_r":  0.00,
        "fringe": 0.00,   # <-- missing fringe
    },
]


def build_row(w):
    st_g = round(w["st_h"] * w["st_r"], 2)
    ot_g = round(w["ot_h"] * w["ot_r"], 2)
    dt_g = round(w["dt_h"] * w["dt_r"], 2)
    tot_h = round(w["st_h"] + w["ot_h"] + w["dt_h"], 2)
    gross = round(st_g + ot_g + dt_g, 2)
    fica = round(gross * 0.0765, 2)
    fed_wh = round(gross * 0.12, 2)
    total_ded = round(fica + fed_wh, 2)
    net = round(gross - total_ded, 2)
    return [
        str(w["row"]), w["last"], w["first"], w["mi"], w["id"], w["j_ra"], w["cls"],
        f"{w['st_h']:.1f}", f"{w['st_r']:.2f}", f"{st_g:.2f}",
        f"{w['ot_h']:.1f}", f"{w['ot_r']:.2f}", f"{ot_g:.2f}",
        f"{w['dt_h']:.1f}", f"{w['dt_r']:.2f}", f"{dt_g:.2f}",
        f"{tot_h:.1f}", f"{gross:.2f}", f"{total_ded:.2f}", f"{net:.2f}",
        f"{w['fringe']:.2f}",
    ]


def generate(output_path: str = "test_payroll.pdf"):
    doc = SimpleDocTemplate(
        output_path,
        pagesize=landscape(letter),
        leftMargin=0.4 * inch,
        rightMargin=0.4 * inch,
        topMargin=0.5 * inch,
        bottomMargin=0.5 * inch,
    )

    styles = getSampleStyleSheet()
    story = []

    # --- Header block ---
    header_data = [
        ["Project Name:", "I-5 Bridge Deck Replacement",
         "Contract No.:", "FHWA-CA-2024-0099",
         "Payroll No.:", "7"],
        ["Project Location:", "Sacramento, CA",
         "Wage Det. No.:", "CA2024-0234",
         "Week Ending:", "06/07/2025"],
        ["Contractor:", "Pacific Coast Builders LLC",
         "Address:", "1440 Harbor Blvd, Stockton CA 95203",
         "", ""],
    ]
    hdr_table = Table(header_data, colWidths=[1.0*inch]*6 + [None])
    hdr_table.setStyle(TableStyle([
        ("FONTNAME",  (0, 0), (-1, -1), "Helvetica"),
        ("FONTSIZE",  (0, 0), (-1, -1), 8),
        ("FONTNAME",  (0, 0), (0, -1), "Helvetica-Bold"),
        ("FONTNAME",  (2, 0), (2, -1), "Helvetica-Bold"),
        ("FONTNAME",  (4, 0), (4, -1), "Helvetica-Bold"),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    story.append(hdr_table)
    story.append(Spacer(1, 0.15 * inch))

    # --- Column headers ---
    col_headers = [
        "#", "Last Name", "First", "MI", "Worker ID", "J/RA", "Classification",
        "ST\nHrs", "ST\nRate", "ST\nGross",
        "OT\nHrs", "OT\nRate", "OT\nGross",
        "DT\nHrs", "DT\nRate", "DT\nGross",
        "Total\nHrs", "Gross", "Deductions", "Net",
        "Fringe\nCredit",
    ]

    # Column widths (total ~10 inches for landscape letter)
    col_w = [
        0.25, 0.85, 0.65, 0.22, 0.55, 0.3, 1.05,
        0.32, 0.42, 0.52,
        0.32, 0.42, 0.52,
        0.32, 0.42, 0.52,
        0.38, 0.52, 0.60, 0.52,
        0.42,
    ]
    col_w = [c * inch for c in col_w]

    table_data = [col_headers] + [build_row(w) for w in workers]

    tbl = Table(table_data, colWidths=col_w, repeatRows=1)
    tbl.setStyle(TableStyle([
        # Header row
        ("BACKGROUND",   (0, 0), (-1, 0), colors.HexColor("#003366")),
        ("TEXTCOLOR",    (0, 0), (-1, 0), colors.white),
        ("FONTNAME",     (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE",     (0, 0), (-1, 0), 7),
        ("ALIGN",        (0, 0), (-1, 0), "CENTER"),
        ("VALIGN",       (0, 0), (-1, 0), "MIDDLE"),
        ("ROWBACKGROUND",(0, 1), (-1, -1), [colors.white, colors.HexColor("#f4f7fb")]),
        # Data rows
        ("FONTNAME",     (0, 1), (-1, -1), "Helvetica"),
        ("FONTSIZE",     (0, 1), (-1, -1), 7.5),
        ("ALIGN",        (7, 1), (-1, -1), "RIGHT"),
        ("ALIGN",        (0, 1), (6, -1), "LEFT"),
        # Grid
        ("GRID",         (0, 0), (-1, -1), 0.4, colors.HexColor("#cccccc")),
        ("LINEBELOW",    (0, 0), (-1, 0), 1.0, colors.HexColor("#003366")),
        ("BOTTOMPADDING",(0, 0), (-1, -1), 3),
        ("TOPPADDING",   (0, 0), (-1, -1), 3),
    ]))
    story.append(tbl)
    story.append(Spacer(1, 0.25 * inch))

    # --- Statement of Compliance (simplified) ---
    compliance_text = (
        "<b>STATEMENT OF COMPLIANCE</b> — I, the undersigned, do hereby state: "
        "That I pay or supervise the payment of the persons employed by "
        "<b>Pacific Coast Builders LLC</b> on the above-referenced contract; "
        "that during the payroll period commencing on June 1, 2025 and ending "
        "June 7, 2025, all persons employed on said project have been paid "
        "the full weekly wages earned, that no rebates have been or will be made "
        "either directly or indirectly to or on behalf of said contractor from the "
        "full weekly wages earned by any person and that no deductions have been made "
        "either directly or indirectly from the full wages earned by any person, "
        "except such payroll deductions as are permitted by regulations issued by "
        "the Secretary of Labor under the Copeland Act."
    )
    story.append(Paragraph(compliance_text, styles["Normal"]))
    story.append(Spacer(1, 0.15 * inch))
    sig_data = [
        ["Signature of Certifying Official:", "James Holloway, Payroll Manager"],
        ["Date:", "06/09/2025"],
        ["Phone:", "(209) 555-0182"],
    ]
    sig_tbl = Table(sig_data, colWidths=[2.0 * inch, 3.5 * inch])
    sig_tbl.setStyle(TableStyle([
        ("FONTSIZE",  (0, 0), (-1, -1), 8),
        ("FONTNAME",  (0, 0), (0, -1), "Helvetica-Bold"),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(sig_tbl)

    doc.build(story)
    print(f"Generated: {output_path}")


if __name__ == "__main__":
    generate()
