"""
Generate a synthetic WH-347 payroll PDF in the LCPtracker / iTextSharp format.

The iTextSharp 27-column layout matches what LCPtracker exports:
  [0]  row#              [1] last   [2] first  [3] MI   [4] worker_id
  [5]  BLANK             [6] J/RA   [7] class  [8] type (ST/OT/DT)
  [9-15] daily hours (Mon-Sun, 7 cols)
  [16] total_hours       [17] rate  [18] fringe_credit
  [19] fringe_lieu       [20] weekly_gross  [21] cumul_gross
  [22] withholding       [23] FICA  [24] other_ded
  [25] total_ded         [26] net

Workers and intentional violations:
  Row 1  MARTINEZ, Carlos  — CARPENTER    J  — PASS (correct rate + OT)
  Row 2  JOHNSON, Bob      — LABORER      J  — FAIL: underpaid ($34.00 vs $36.50)
  Row 3  CHEN, Wei         — IRONWORKER   RA — WARN: cert needed (period 2 inferred)
  Row 4  TORRES, Maria     — OPERATOR     J  — FAIL: 50 hrs all ST (CWHSSA violation)
  Row 5  SMITH, David      — ELECTRICIAN  J  — FAIL: fringe $0 (required ~$24.47/hr)
"""

from reportlab.lib import colors
from reportlab.lib.pagesizes import landscape, letter
from reportlab.lib.units import inch
from reportlab.platypus import SimpleDocTemplate, Spacer, Table, TableStyle

# ---------------------------------------------------------------------------
# Column widths (27 cols, total ~9.8" for landscape letter minus margins)
# ---------------------------------------------------------------------------
_W = [w * inch for w in [
    0.22,                           # 0  row #
    0.80, 0.60, 0.18, 0.45,        # 1-4 name fields
    0.20,                           # 5  BLANK
    0.22, 0.92, 0.22,              # 6-8 J/RA, classification, type
    0.23, 0.23, 0.23, 0.23, 0.23, 0.23, 0.23,  # 9-15 Mon-Sun hours
    0.32,                           # 16 total hrs
    0.42, 0.40, 0.30,              # 17-19 rate, fringe credit, fringe lieu
    0.52, 0.40,                    # 20-21 weekly gross, cumul gross
    0.42, 0.38, 0.38, 0.40, 0.48, # 22-26 withhold, FICA, other, total ded, net
]]


# ---------------------------------------------------------------------------
# Payroll data helpers
# ---------------------------------------------------------------------------

def _blank(n=27):
    return [''] * n


def _header_label_row():
    r = _blank()
    r[0]  = 'PROJECT NAME'
    r[5]  = 'CONTRACT NO.'
    r[9]  = 'PAYROLL NO.'
    r[16] = 'NAME OF CONTRACTOR'
    return r


def _header_value_row():
    r = _blank()
    r[0]  = 'I-5 Bridge Deck Replacement'
    r[5]  = 'FHWA-CA-2024-0099'
    r[9]  = '7'
    r[16] = 'Pacific Coast Builders LLC'
    return r


def _header_label_row2():
    r = _blank()
    r[0]  = 'PROJECT LOCATION'
    r[5]  = 'WAGE DETERMINATION NO.'
    r[9]  = 'WEEK ENDING'
    r[16] = 'CONTRACTOR ADDRESS'
    return r


def _header_value_row2():
    r = _blank()
    r[0]  = 'Sacramento, CA'
    r[5]  = 'CA2024-0234'
    r[9]  = '06/07/2025'
    r[16] = '1440 Harbor Blvd, Stockton CA 95203'
    return r


def _col_header_row():
    r = _blank()
    r[0]  = '#'
    r[1]  = 'LAST NAME'
    r[2]  = 'FIRST'
    r[3]  = 'MI'
    r[4]  = 'WORKER ID'
    r[5]  = ''
    r[6]  = 'J/RA'
    r[7]  = 'CLASSIFICATION'
    r[8]  = 'TYPE'
    r[9]  = 'MON'
    r[10] = 'TUE'
    r[11] = 'WED'
    r[12] = 'THU'
    r[13] = 'FRI'
    r[14] = 'SAT'
    r[15] = 'SUN'
    r[16] = 'TOTAL HRS'
    r[17] = 'RATE'
    r[18] = 'FRINGE CR'
    r[19] = 'FRINGE LIEU'
    r[20] = 'WEEKLY GROSS'
    r[21] = 'CUMUL GROSS'
    r[22] = 'FED W/H'
    r[23] = 'FICA'
    r[24] = 'OTHER DED'
    r[25] = 'TOTAL DED'
    r[26] = 'NET PAY'
    return r


def _worker_st_row(row_num, last, first, mi, worker_id, j_ra, cls,
                   daily_hrs, total_hrs, rate, fringe_cr,
                   weekly_gross, withhold, fica):
    r = _blank()
    r[0]  = str(row_num)
    r[1]  = last
    r[2]  = first
    r[3]  = mi
    r[4]  = worker_id
    r[5]  = ''
    r[6]  = j_ra
    r[7]  = cls
    r[8]  = 'ST'
    for i, h in enumerate(daily_hrs):
        r[9 + i] = str(h) if h else ''
    r[16] = f'{total_hrs:.1f}'
    r[17] = f'{rate:.2f}'
    r[18] = f'{fringe_cr:.2f}' if fringe_cr else ''
    r[19] = ''
    r[20] = f'{weekly_gross:.2f}'
    r[21] = ''
    r[22] = f'{withhold:.2f}'
    r[23] = f'{fica:.2f}'
    r[24] = ''
    r[25] = ''        # YTD deductions — left blank; parser sets deductions=0
    r[26] = f'{weekly_gross:.2f}'  # net = gross (parser ignores YTD deductions)
    return r


def _worker_ot_row(daily_hrs, rate):
    r = _blank()
    r[8] = 'OT'
    for i, h in enumerate(daily_hrs):
        r[9 + i] = str(h) if h else ''
    r[17] = f'{rate:.2f}'
    return r


def _worker_dt_row(daily_hrs, rate):
    r = _blank()
    r[8] = 'DT'
    for i, h in enumerate(daily_hrs):
        r[9 + i] = str(h) if h else ''
    r[17] = f'{rate:.2f}'
    return r


# ---------------------------------------------------------------------------
# Build payroll rows
# ---------------------------------------------------------------------------

def _payroll_rows():
    rows = []

    # Row 1 — MARTINEZ, Carlos — CARPENTER J — PASS (correct, 40 ST + 5 OT)
    st_rate = 44.50
    ot_rate = round(st_rate * 1.5, 2)
    st_hrs  = [8, 8, 8, 8, 8, 0, 0]   # Mon-Sun
    ot_hrs  = [0, 0, 0, 0, 5, 0, 0]
    gross   = round(sum(st_hrs) * st_rate + sum(ot_hrs) * ot_rate, 2)
    rows.append(_worker_st_row(
        1, 'MARTINEZ', 'CARLOS', 'R', 'E-1001', 'J', 'CARPENTER',
        st_hrs, 45.0, st_rate, 15.85, gross,
        round(gross * 0.12, 2), round(gross * 0.0765, 2),
    ))
    rows.append(_worker_ot_row(ot_hrs, ot_rate))

    # Row 2 — JOHNSON, Bob — LABORER J — FAIL: $34.00 < required $36.50
    st_rate = 34.00   # underpaid
    gross   = round(40 * st_rate, 2)
    rows.append(_worker_st_row(
        2, 'JOHNSON', 'BOB', 'K', 'E-1002', 'J', 'LABORER',
        [8, 8, 8, 8, 8, 0, 0], 40.0, st_rate, 13.25, gross,
        round(gross * 0.12, 2), round(gross * 0.0765, 2),
    ))

    # Row 3 — CHEN, Wei — IRONWORKER RA — WARN: no cert (period 2 inferred)
    st_rate = 35.62   # 65% of $54.80 journeyman rate (period 2)
    gross   = round(40 * st_rate, 2)
    rows.append(_worker_st_row(
        3, 'CHEN', 'WEI', 'L', 'E-1003', 'RA', 'IRONWORKER',
        [8, 8, 8, 8, 8, 0, 0], 40.0, st_rate, 17.42, gross,
        round(gross * 0.12, 2), round(gross * 0.0765, 2),
    ))

    # Row 4 — TORRES, Maria — OPERATOR J — FAIL: 50 hrs all ST (CWHSSA)
    st_rate = 58.30
    daily   = [8, 8, 8, 8, 8, 5, 3]   # 50 hrs, no OT declared
    gross   = round(sum(daily) * st_rate, 2)
    rows.append(_worker_st_row(
        4, 'TORRES', 'MARIA', 'E', 'E-1004', 'J', 'OPERATOR',
        daily, float(sum(daily)), st_rate, 19.15, gross,
        round(gross * 0.12, 2), round(gross * 0.0765, 2),
    ))

    # Row 5 — SMITH, David — ELECTRICIAN J — FAIL: fringe $0
    st_rate = 57.45
    gross   = round(40 * st_rate, 2)
    rows.append(_worker_st_row(
        5, 'SMITH', 'DAVID', 'A', 'E-1005', 'J', 'ELECTRICIAN',
        [8, 8, 8, 8, 8, 0, 0], 40.0, st_rate, 0.00, gross,
        round(gross * 0.12, 2), round(gross * 0.0765, 2),
    ))

    return rows


# ---------------------------------------------------------------------------
# Table style helpers
# ---------------------------------------------------------------------------

DARK_BLUE = colors.HexColor('#003366')
LIGHT_GRAY = colors.HexColor('#f4f7fb')
MID_GRAY   = colors.HexColor('#dee2e6')

_BASE_STYLE = [
    ('FONTNAME',     (0, 0), (-1, -1), 'Helvetica'),
    ('FONTSIZE',     (0, 0), (-1, -1), 6.5),
    ('GRID',         (0, 0), (-1, -1), 0.3, MID_GRAY),
    ('TOPPADDING',   (0, 0), (-1, -1), 2),
    ('BOTTOMPADDING',(0, 0), (-1, -1), 2),
]


def _main_table_style(n_data_rows):
    style = list(_BASE_STYLE)

    # Merge header label/value zones so pdfplumber reads each zone as one cell.
    # Zone boundaries: project(0-4), contract(5-8), payroll(9-15), contractor(16-26)
    zones = [(0, 4), (5, 8), (9, 15), (16, 26)]
    for row in range(4):          # rows 0-3 are the header label+value rows
        for start, end in zones:
            style.append(('SPAN', (start, row), (end, row)))

    # Header block styling (rows 0-3)
    style += [
        ('BACKGROUND', (0, 0), (-1, 3), colors.HexColor('#e8ecf0')),
        ('FONTNAME',   (0, 0), (-1, 3), 'Helvetica-Bold'),
        ('FONTSIZE',   (0, 0), (-1, 3), 7),
        ('TOPPADDING', (0, 0), (-1, 3), 4),
        ('BOTTOMPADDING', (0, 0), (-1, 3), 4),
    ]
    # Column header row (row 4)
    style += [
        ('BACKGROUND', (0, 4), (-1, 4), DARK_BLUE),
        ('TEXTCOLOR',  (0, 4), (-1, 4), colors.white),
        ('FONTNAME',   (0, 4), (-1, 4), 'Helvetica-Bold'),
        ('FONTSIZE',   (0, 4), (-1, 4), 5.5),
        ('ALIGN',      (0, 4), (-1, 4), 'CENTER'),
    ]
    # Alternate row shading for data rows
    for i in range(5, 5 + n_data_rows, 2):
        style.append(('BACKGROUND', (0, i), (-1, i), LIGHT_GRAY))
    return TableStyle(style)


# ---------------------------------------------------------------------------
# Compliance / signature table
# ---------------------------------------------------------------------------

def _compliance_table():
    """
    5-column table that the iTextSharp parser recognises via
    'SIGNATURE OF CERTIFYING OFFICIAL' in cell[0] of the label row.
    """
    label_row = [
        'SIGNATURE OF CERTIFYING OFFICIAL',
        'TITLE',
        'DATE',
        'PHONE',
        'EMAIL',
    ]
    value_row = [
        'James Holloway',
        'Payroll Manager',
        '06/09/2025',
        '(209) 555-0182',
        'jholloway@pcbuilders.com',
    ]
    # Also add a CERTIFYING OFFICIAL name/title row (picked up by the
    # name+title parser branch that looks for 'CERTIFYING OFFICIAL').
    certifying_label = [
        'CERTIFYING OFFICIAL (Name / Title)',
        '', '', '', '',
    ]
    certifying_value = [
        'James Holloway / Payroll Manager',
        '', '', '', '',
    ]

    data = [certifying_label, certifying_value, label_row, value_row]
    col_w = [2.5 * inch, 1.5 * inch, 1.0 * inch, 1.2 * inch, 2.0 * inch]

    tbl = Table(data, colWidths=col_w)
    tbl.setStyle(TableStyle([
        ('FONTNAME',     (0, 0), (-1, -1), 'Helvetica'),
        ('FONTSIZE',     (0, 0), (-1, -1), 8),
        ('FONTNAME',     (0, 0), (0, -1), 'Helvetica-Bold'),
        ('FONTNAME',     (0, 2), (-1, 2), 'Helvetica-Bold'),
        ('GRID',         (0, 0), (-1, -1), 0.4, MID_GRAY),
        ('BACKGROUND',   (0, 0), (-1, 0), colors.HexColor('#e8ecf0')),
        ('BACKGROUND',   (0, 2), (-1, 2), colors.HexColor('#e8ecf0')),
        ('TOPPADDING',   (0, 0), (-1, -1), 3),
        ('BOTTOMPADDING',(0, 0), (-1, -1), 3),
    ]))
    return tbl


# ---------------------------------------------------------------------------
# Main generator
# ---------------------------------------------------------------------------

def generate(output_path: str = 'test_payroll.pdf'):
    doc = SimpleDocTemplate(
        output_path,
        pagesize=landscape(letter),
        leftMargin=0.4 * inch,
        rightMargin=0.4 * inch,
        topMargin=0.5 * inch,
        bottomMargin=0.5 * inch,
    )

    payroll_rows = _payroll_rows()
    table_data = (
        [_header_label_row(),       # row 0 — "PROJECT NAME" triggers header parse
         _header_value_row(),        # row 1 — header values
         _header_label_row2(),       # row 2 — second label row
         _header_value_row2(),       # row 3 — second value row (week ending, wage det.)
         _col_header_row()]          # row 4 — column headers
        + payroll_rows               # rows 5+ — worker ST/OT/DT data
    )

    main_table = Table(table_data, colWidths=_W, repeatRows=5)
    main_table.setStyle(_main_table_style(len(payroll_rows)))

    story = [
        main_table,
        Spacer(1, 0.25 * inch),
        _compliance_table(),
    ]
    doc.build(story)
    print(f'Generated: {output_path}')


if __name__ == '__main__':
    generate()
