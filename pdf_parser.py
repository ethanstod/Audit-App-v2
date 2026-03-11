import pdfplumber
import re
import os
from datetime import datetime


# ---------------------------------------------------------------------------
# FreeText annotation extractor (for Jan 2025 DOL WH-347 form)
# ---------------------------------------------------------------------------

def _get_freetext_annotations(pdf_path):
    """
    Extracts all FreeText annotations from all pages of the PDF.
    Returns a list of dicts: {page, x0, y0, x1, y1, content}
    """
    from pdfminer.pdfdocument import PDFDocument
    from pdfminer.pdfparser import PDFParser
    from pdfminer.pdftypes import resolve1
    from pdfminer.pdfpage import PDFPage

    def decode(v):
        if isinstance(v, bytes):
            return v.decode('utf-8', errors='replace')
        return str(v) if v is not None else ''

    annotations = []

    with open(pdf_path, 'rb') as f:
        parser = PDFParser(f)
        doc = PDFDocument(parser)

        for page_num, page in enumerate(PDFPage.create_pages(doc), 1):
            if not page.annots:
                continue
            annots_resolved = resolve1(page.annots)
            if not annots_resolved:
                continue

            for annot_ref in annots_resolved:
                annot = resolve1(annot_ref)
                if not isinstance(annot, dict):
                    continue
                subtype = decode(annot.get('Subtype', ''))
                if 'FreeText' not in subtype:
                    continue
                contents = decode(annot.get('Contents', '')).strip()
                if not contents:
                    continue
                rect = annot.get('Rect', [0, 0, 0, 0])
                try:
                    rect = [float(v) for v in rect]
                    x0, y0, x1, y1 = rect
                except (TypeError, ValueError):
                    continue

                annotations.append({
                    'page': page_num,
                    'x0': x0, 'y0': y0,
                    'x1': x1, 'y1': y1,
                    'content': contents,
                })

    return annotations


# ---------------------------------------------------------------------------
# X-coordinate column map for WH-347 worker rows (Jan 2025 DOL form)
# Based on empirical measurement from wh347_test_complete.pdf
# ---------------------------------------------------------------------------
_WORKER_COL_RANGES = {
    'row_number':       (0,    66),
    'last_name':        (66,   118),
    'first_name':       (118,  165),
    'middle_initial':   (165,  193),
    'worker_id':        (193,  228),
    'j_ra':             (228,  260),
    'classification':   (260,  341),
    # day-by-day hours sit between x=341-430; OT sub-row at x~405-430
    'ot_hours_sub':     (400,  430),
    'total_hours':      (430,  462),
    'st_rate':          (462,  503),
    'fringe_credit':    (503,  530),
    # x 530-597 not mapped (unused / always 0 in known forms)
    'gross':            (597,  637),
    'fica':             (637,  666),
    'withholding':      (666,  697),
    'total_deductions': (697,  727),
    'net':              (727,  800),
}


def _x_to_col(x0):
    """Returns the field name for a given x0 coordinate, or None."""
    for col, (lo, hi) in _WORKER_COL_RANGES.items():
        if lo <= x0 < hi:
            return col
    return None


def _safe_float(val):
    try:
        return float(str(val).replace(',', '').strip())
    except (ValueError, TypeError):
        return 0.0


# ---------------------------------------------------------------------------
# FreeText-based header extractor
# ---------------------------------------------------------------------------

def _extract_header_from_annotations(annots, page_num=1):
    """
    Extracts WH-347 form header from FreeText annotations on the given page.

    On the Jan 2025 DOL form (page 1):
      Upper header band (y ~455-480):
        x<200:       project name
        200<x<342:   contract number
        342<x<444:   payroll number
        x>444:       contractor business name
      Lower header band (y ~425-450):
        x<200:       project location
        200<x<342:   wage determination number
        342<x<444:   week ending date
        x>444:       contractor business address
    """
    header = {
        'contractor_name':          '',
        'contractor_address':       '',
        'payroll_number':           '',
        'week_ending':              '',
        'project_name':             '',
        'project_location':         '',
        'contract_number':          '',
        'wage_determination_number': '',
    }

    page_annots = [a for a in annots if a['page'] == page_num]

    # Detect header y-band automatically: look for high-y FreeText blocks
    # that are clearly above the worker rows (y0 > 350 typically)
    header_annots = [a for a in page_annots if a['y0'] > 350]

    if not header_annots:
        # Fallback: use the two highest y-bands found
        if page_annots:
            sorted_y = sorted({round(a['y0'] / 20) * 20 for a in page_annots}, reverse=True)
            if sorted_y:
                top_y = sorted_y[0] * 1.0
                header_annots = [a for a in page_annots if a['y0'] >= top_y - 40]

    for a in header_annots:
        x0, y0 = a['x0'], a['y0']
        val = a['content']

        # Use two y-bands based on relative position
        # Upper band: higher y0 values
        upper_band = any(
            b['y0'] > y0 + 10 for b in header_annots
        ) is False  # this is the topmost group

        if x0 < 200:
            if not header['project_name']:
                header['project_name'] = val
            elif not header['project_location']:
                header['project_location'] = val
        elif 200 <= x0 < 342:
            if not header['contract_number']:
                header['contract_number'] = val
            elif not header['wage_determination_number']:
                header['wage_determination_number'] = val
        elif 342 <= x0 < 444:
            # Payroll number or week ending
            if re.match(r'^\d+$', val.strip()):
                header['payroll_number'] = val.strip()
            elif re.search(r'\d{1,2}[/\-]\d{1,2}[/\-]\d{2,4}', val):
                header['week_ending'] = val.strip()
            elif not header['payroll_number']:
                header['payroll_number'] = val.strip()
        elif x0 >= 444:
            if not header['contractor_name']:
                header['contractor_name'] = val
            elif not header['contractor_address']:
                header['contractor_address'] = val

    # Second pass: try to split by y proximity (two y bands)
    if header_annots:
        y_values = sorted({a['y0'] for a in header_annots}, reverse=True)
        if len(y_values) >= 2:
            upper_y = y_values[0]
            lower_y = next((y for y in y_values if upper_y - y > 10), upper_y - 30)

            upper = [a for a in header_annots if abs(a['y0'] - upper_y) < 10]
            lower = [a for a in header_annots if abs(a['y0'] - lower_y) < 10]

            for a in upper:
                x0, val = a['x0'], a['content']
                if x0 < 200:
                    header['project_name'] = val
                elif 200 <= x0 < 342:
                    header['contract_number'] = val
                elif 342 <= x0 < 444:
                    if re.match(r'^\d+$', val.strip()):
                        header['payroll_number'] = val.strip()
                    else:
                        header['payroll_number'] = val.strip()
                elif x0 >= 444:
                    header['contractor_name'] = val

            for a in lower:
                x0, val = a['x0'], a['content']
                if x0 < 200:
                    header['project_location'] = val
                elif 200 <= x0 < 342:
                    header['wage_determination_number'] = val
                elif 342 <= x0 < 444:
                    if re.search(r'\d{1,2}[/\-]\d{1,2}[/\-]\d{2,4}', val):
                        header['week_ending'] = val.strip()
                elif x0 >= 444:
                    header['contractor_address'] = val

    return header


# ---------------------------------------------------------------------------
# FreeText-based compliance statement extractor
# ---------------------------------------------------------------------------

def _extract_compliance_from_annotations(annots, total_pages):
    """
    Extracts the Statement of Compliance fields from page 2 (or last page).
    On the Jan 2025 form, page 2 contains:
      - Project header (repeat)
      - Certifying official name/title
      - Signature name, date, phone, email (lowest y-values on page 2)
    """
    result = {
        'certified_signature': False,
        'certified_name': '',
        'certified_title': '',
        'certified_date': '',
        'detected_by_text': False,
    }

    page2_annots = [a for a in annots if a['page'] == total_pages]
    if not page2_annots:
        # Try any page beyond page 1
        other = [a for a in annots if a['page'] > 1]
        if other:
            page2_annots = other

    if not page2_annots:
        return result

    # The certifying official name+title appears at mid-page in the header repeat
    # The signature block appears at the bottom (lowest y values)
    y_sorted = sorted(page2_annots, key=lambda a: a['y0'])
    bottom_annots = y_sorted[:6]  # lowest 6 items = signature block

    for a in bottom_annots:
        val = a['content']
        # Detect date
        if re.search(r'\d{1,2}[/\-]\d{1,2}[/\-]\d{2,4}', val):
            result['certified_date'] = val.strip()
            result['certified_signature'] = True
            result['detected_by_text'] = True
        # Detect phone
        elif re.search(r'\(\d{3}\)\s*\d{3}[-.\s]\d{4}', val):
            pass  # phone, not a signature field
        # Detect email
        elif '@' in val:
            pass
        # Name (first item without digits usually)
        elif not result['certified_name'] and not any(c.isdigit() for c in val):
            result['certified_name'] = val.strip()
            result['certified_signature'] = True
            result['detected_by_text'] = True

    # Certifying official with title appears in a mid-page annotation (page 2)
    mid_annots = [a for a in page2_annots if a['y0'] > 50]
    for a in sorted(mid_annots, key=lambda a: -a['y0'])[:4]:
        val = a['content']
        if a['x0'] > 400 and ',' in val and not result['certified_title']:
            # "James Holloway, Project Manager" style
            parts = val.split(',', 1)
            if len(parts) == 2:
                result['certified_name'] = parts[0].strip()
                result['certified_title'] = parts[1].strip()
                result['certified_signature'] = True
                result['detected_by_text'] = True

    return result


# ---------------------------------------------------------------------------
# Worker row extractor from FreeText annotations
# ---------------------------------------------------------------------------

def _extract_workers_from_annotations(annots, page_num=1):
    """
    Groups FreeText annotations into worker rows by y-position,
    then maps each annotation to a field using x-coordinate ranges.
    """
    page_annots = [a for a in annots if a['page'] == page_num]

    # Find row-number annotations (x < 66, numeric content)
    row_markers = [
        a for a in page_annots
        if a['x0'] < 66 and re.match(r'^\d+$', a['content'].strip())
    ]

    if not row_markers:
        return []

    workers = []

    for marker in row_markers:
        row_num = int(marker['content'].strip())
        row_y0 = marker['y0']
        row_y1 = marker['y1']
        # Collect all annotations within this row's y-band (+/- tolerance)
        band_lo = row_y0 - 5
        band_hi = row_y1 + 5

        row_annots = [
            a for a in page_annots
            if a['y0'] >= band_lo and a['y1'] <= band_hi + 10
        ]

        worker = {
            'row_number':         row_num,
            'last_name':          '',
            'first_name':         '',
            'middle_initial':     '',
            'worker_id':          '',
            'j_ra':               '',
            'classification':     '',
            'st_hours':           0.0,
            'ot_hours':           0.0,
            'dt_hours':           0.0,
            'total_hours':        0.0,
            'st_rate':            0.0,
            'ot_rate':            0.0,
            'dt_rate':            0.0,
            'rate':               0.0,
            'st_gross':           0.0,
            'ot_gross':           0.0,
            'dt_gross':           0.0,
            'gross':              0.0,
            'fica':               0.0,
            'withholding':        0.0,
            'deductions':         0.0,
            'net':                0.0,
            'fringe_paid_cash':   0.0,
            'fringe_plan_name':   '',
            'fringe_plan_amount': 0.0,
            'apprentice_program_name': '',
            'apprentice_period':  0,
            'apprentice_percent': 0.0,
        }

        for a in row_annots:
            col = _x_to_col(a['x0'])
            if col is None:
                continue
            val = a['content'].strip()

            if col == 'row_number':
                pass  # already set
            elif col == 'last_name':
                worker['last_name'] = val.title()
            elif col == 'first_name':
                worker['first_name'] = val.title()
            elif col == 'middle_initial':
                worker['middle_initial'] = val
            elif col == 'worker_id':
                worker['worker_id'] = val
            elif col == 'j_ra':
                worker['j_ra'] = val.upper()
            elif col == 'classification':
                worker['classification'] = val
            elif col == 'ot_hours_sub':
                worker['ot_hours'] = _safe_float(val)
            elif col == 'total_hours':
                worker['total_hours'] = _safe_float(val)
            elif col == 'st_rate':
                worker['st_rate'] = _safe_float(val)
                worker['rate'] = worker['st_rate']
            elif col == 'fringe_credit':
                worker['fringe_paid_cash'] = _safe_float(val)
            elif col == 'gross':
                worker['gross'] = _safe_float(val)
            elif col == 'fica':
                worker['fica'] = _safe_float(val)
            elif col == 'withholding':
                worker['withholding'] = _safe_float(val)
            elif col == 'total_deductions':
                worker['deductions'] = _safe_float(val)
            elif col == 'net':
                worker['net'] = _safe_float(val)

        # Derive ST hours and rates
        worker['st_hours'] = round(worker['total_hours'] - worker['ot_hours'], 2)
        if worker['st_hours'] < 0:
            worker['st_hours'] = 0.0

        # Compute OT rate
        if worker['st_rate'] > 0:
            worker['ot_rate'] = round(worker['st_rate'] * 1.5, 2)
            worker['dt_rate'] = round(worker['st_rate'] * 2.0, 2)

        # Estimate ST/OT gross components
        worker['st_gross'] = round(worker['st_hours'] * worker['st_rate'], 2)
        worker['ot_gross'] = round(worker['ot_hours'] * worker['ot_rate'], 2)

        workers.append(worker)

    return workers


# ---------------------------------------------------------------------------
# Legacy text-based header extractor (fallback for non-annotation PDFs)
# ---------------------------------------------------------------------------

def extract_wh347_header(pdf_path):
    header = {
        'contractor_name':          '',
        'contractor_address':       '',
        'payroll_number':           '',
        'week_ending':              '',
        'project_name':             '',
        'project_location':         '',
        'contract_number':          '',
        'wage_determination_number': '',
    }

    with pdfplumber.open(pdf_path) as pdf:
        if not pdf.pages:
            return header
        page = pdf.pages[0]
        height = page.height
        header_region = page.crop((0, 0, page.width, min(200, height * 0.35)))
        text = header_region.extract_text() or ''
        full_text = page.extract_text() or ''
        search_text = text + '\n' + full_text

    def find_value(pattern, text, group=1, default=''):
        m = re.search(pattern, text, re.IGNORECASE)
        return m.group(group).strip() if m else default

    header['contractor_name'] = find_value(
        r'Contractor[:\s]+([A-Za-z0-9\s&,\.\-\']+?)(?:\n|Address|$)', search_text)
    header['contractor_address'] = find_value(r'Address[:\s]+([^\n]+)', search_text)
    header['payroll_number'] = find_value(
        r'Payroll\s*(?:No\.?|Number)[:\s#]*(\d+)', search_text)
    header['week_ending'] = find_value(
        r'Week\s*Ending[:\s]+(\d{1,2}[/\-]\d{1,2}[/\-]\d{2,4})', search_text)
    header['project_name'] = find_value(
        r'Project\s*(?:and\s*Location|Name)?[:\s]+([^\n]+)', search_text)
    header['contract_number'] = find_value(
        r'Contract\s*(?:No\.?|Number)[:\s]+([A-Z0-9\-]+)', search_text)
    header['wage_determination_number'] = find_value(
        r'Wage\s*Det(?:ermination)?[:\s#.]*([A-Z]{2}\d{7,})', search_text)

    return header


def extract_compliance_statement(pdf_path):
    result = {
        'certified_signature': False,
        'certified_name':      '',
        'certified_title':     '',
        'certified_date':      '',
        'detected_by_text':    False,
    }

    with pdfplumber.open(pdf_path) as pdf:
        if not pdf.pages:
            return result
        last_page = pdf.pages[-1]
        text = last_page.extract_text() or ''
        search_text = text
        if len(pdf.pages) == 1:
            search_text = (pdf.pages[0].extract_text() or '')

    cert_keywords = ['certify', 'penalties of perjury', 'statement of compliance',
                     'willful falsification', 'i, the undersigned']
    if any(kw in search_text.lower() for kw in cert_keywords):
        result['detected_by_text'] = True
        name_m = re.search(
            r'(?:Signature|Signed|Name)[:\s]+([A-Za-z\s\.\-\']{3,50}?)(?:\n|Title|Date)',
            search_text, re.IGNORECASE)
        if name_m:
            result['certified_name'] = name_m.group(1).strip()
            result['certified_signature'] = True
        date_m = re.search(
            r'Date[:\s]+(\d{1,2}[/\-]\d{1,2}[/\-]\d{2,4})',
            search_text, re.IGNORECASE)
        if date_m:
            result['certified_date'] = date_m.group(1).strip()
            result['certified_signature'] = True

    return result


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def extract_wh347_data(pdf_path):
    """
    Extracts WH-347 payroll data from a PDF.

    Strategy:
    1. Try FreeText annotation extraction (handles Jan 2025 DOL official form).
    2. Fall back to pdfplumber table extraction.
    3. Fall back to raw text parsing.

    Returns:
    {
        'header': {...},
        'lines': [...],
        'totals': {...},
        'compliance_statement': {...}
    }
    """

    if not os.path.exists(pdf_path):
        raise FileNotFoundError(f'File not found: {pdf_path}')

    def safe_float(val):
        try:
            return float(str(val).replace(',', '').strip())
        except (ValueError, TypeError):
            return 0.0

    def clean_cell(cell):
        return str(cell).strip() if cell else ''

    # -------------------------------------------------------------------------
    # Attempt 1: FreeText annotation extraction
    # -------------------------------------------------------------------------
    parsed_rows = []
    header = {}
    compliance_statement = {}

    try:
        annots = _get_freetext_annotations(pdf_path)
        if annots:
            with pdfplumber.open(pdf_path) as pdf:
                total_pages = len(pdf.pages)

            # Extract header from page 1
            header = _extract_header_from_annotations(annots, page_num=1)

            # Extract workers from all pages except last (compliance page)
            worker_pages = range(1, total_pages + 1) if total_pages == 1 else range(1, total_pages)
            for pg in worker_pages:
                rows = _extract_workers_from_annotations(annots, page_num=pg)
                parsed_rows.extend(rows)

            # Extract compliance statement from last page
            compliance_statement = _extract_compliance_from_annotations(annots, total_pages)

    except Exception as e:
        print(f'[!] FreeText extraction error: {e} -- trying table mode')

    # -------------------------------------------------------------------------
    # Attempt 2: pdfplumber table extraction
    # -------------------------------------------------------------------------
    if not parsed_rows:
        with pdfplumber.open(pdf_path) as pdf:
            for page_number, page in enumerate(pdf.pages, start=1):
                tables = page.extract_tables()
                for table in tables:
                    if not table:
                        continue
                    for row in table:
                        if not row:
                            continue
                        cleaned = [clean_cell(c) for c in row]
                        if not cleaned[0].isdigit():
                            continue
                        try:
                            row_number = int(cleaned[0])
                            last_name = cleaned[1].title() if len(cleaned) > 1 else ''
                            first_name = cleaned[2].title() if len(cleaned) > 2 else ''
                            middle_initial = cleaned[3] if len(cleaned) > 3 else ''
                            worker_id = cleaned[4] if len(cleaned) > 4 else ''
                            j_ra = cleaned[5] if len(cleaned) > 5 else ''
                            classification = cleaned[6] if len(cleaned) > 6 else ''

                            num_cols = len(cleaned)
                            if num_cols >= 20:
                                st_hours = safe_float(cleaned[7])
                                st_rate = safe_float(cleaned[8])
                                st_gross = safe_float(cleaned[9])
                                ot_hours = safe_float(cleaned[10])
                                ot_rate = safe_float(cleaned[11])
                                ot_gross = safe_float(cleaned[12])
                                dt_hours = safe_float(cleaned[13])
                                dt_rate = safe_float(cleaned[14])
                                dt_gross = safe_float(cleaned[15])
                                total_hours = safe_float(cleaned[16])
                                gross = safe_float(cleaned[17])
                                deductions = safe_float(cleaned[18])
                                net = safe_float(cleaned[19])
                                fringe_cash = safe_float(cleaned[20]) if num_cols > 20 else 0.0
                            else:
                                st_hours = safe_float(cleaned[7]) if len(cleaned) > 7 else 0.0
                                ot_hours = safe_float(cleaned[8]) if len(cleaned) > 8 else 0.0
                                dt_hours = safe_float(cleaned[9]) if len(cleaned) > 9 else 0.0
                                total_hours = safe_float(cleaned[10]) if len(cleaned) > 10 else 0.0
                                st_rate = safe_float(cleaned[11]) if len(cleaned) > 11 else 0.0
                                ot_rate = round(st_rate * 1.5, 2)
                                dt_rate = round(st_rate * 2.0, 2)
                                gross = safe_float(cleaned[12]) if len(cleaned) > 12 else 0.0
                                st_gross = gross
                                ot_gross = 0.0
                                dt_gross = 0.0
                                deductions = safe_float(cleaned[13]) if len(cleaned) > 13 else 0.0
                                net = safe_float(cleaned[14]) if len(cleaned) > 14 else 0.0
                                fringe_cash = 0.0

                        except Exception:
                            continue

                        parsed_rows.append({
                            'row_number': row_number,
                            'first_name': first_name,
                            'last_name': last_name,
                            'middle_initial': middle_initial,
                            'worker_id': worker_id,
                            'j_ra': j_ra,
                            'classification': classification,
                            'st_hours': st_hours,
                            'ot_hours': ot_hours,
                            'dt_hours': dt_hours,
                            'total_hours': total_hours,
                            'st_rate': st_rate,
                            'ot_rate': ot_rate,
                            'dt_rate': dt_rate,
                            'rate': st_rate,
                            'st_gross': st_gross,
                            'ot_gross': ot_gross,
                            'dt_gross': dt_gross,
                            'gross': gross,
                            'deductions': deductions,
                            'net': net,
                            'fringe_paid_cash': fringe_cash,
                            'fringe_plan_name': '',
                            'fringe_plan_amount': 0.0,
                            'apprentice_program_name': '',
                            'apprentice_period': 0,
                            'apprentice_percent': 0.0,
                        })

    # -------------------------------------------------------------------------
    # Attempt 3: Fallback text parser
    # -------------------------------------------------------------------------
    if not parsed_rows:
        print('[!] No structured data found -- using fallback text parser.')
        lines = []
        with pdfplumber.open(pdf_path) as pdf:
            for page in pdf.pages:
                text = page.extract_text() or ''
                for raw in text.splitlines():
                    cleaned_line = re.sub(r'\s+', ' ', raw.strip())
                    if cleaned_line:
                        lines.append(cleaned_line)

        worker_blocks = []
        current = []
        for line in lines:
            if re.match(r'^\d+\s+[A-Z]', line):
                if current:
                    worker_blocks.append(current)
                current = [line]
            else:
                if current:
                    current.append(line)
        if current:
            worker_blocks.append(current)

        name_pattern = re.compile(
            r'^(\d+)\s+([A-Z\-\']+)\s+([A-Z\-\']+)\s*([A-Z]?)\s+([A-Z0-9]{3,})\s+(J|RA)'
        )

        for block in worker_blocks:
            match = name_pattern.match(block[0])
            if not match:
                continue

            row_number = int(match.group(1))
            last_name = match.group(2).title()
            first_name = match.group(3).title()
            middle_initial = match.group(4)
            worker_id = match.group(5)
            j_ra = match.group(6)

            st = {'hours': 0.0, 'rate': 0.0, 'gross': 0.0, 'deductions': 0.0, 'net': 0.0}
            ot = {'hours': 0.0, 'rate': 0.0, 'gross': 0.0, 'deductions': 0.0, 'net': 0.0}
            dt = {'hours': 0.0, 'rate': 0.0, 'gross': 0.0, 'deductions': 0.0, 'net': 0.0}

            for line in block:
                type_match = re.search(r'\b(ST|OT|DT)\b', line)
                if not type_match:
                    continue
                nums = re.findall(r'\d+\.\d+', line)
                if len(nums) < 5:
                    continue
                nums = [safe_float(n) for n in nums]
                record = {
                    'hours': nums[-5], 'rate': nums[-4], 'gross': nums[-3],
                    'deductions': nums[-2], 'net': nums[-1],
                }
                t = type_match.group(1)
                if t == 'ST':
                    st = record
                elif t == 'OT':
                    ot = record
                elif t == 'DT':
                    dt = record

            st_rate = st['rate']
            ot_rate = ot['rate'] if ot['rate'] > 0 else round(st_rate * 1.5, 2)
            dt_rate = dt['rate'] if dt['rate'] > 0 else round(st_rate * 2.0, 2)
            total_hours = st['hours'] + ot['hours'] + dt['hours']
            gross_total = st['gross'] + ot['gross'] + dt['gross']

            parsed_rows.append({
                'row_number':    row_number,
                'first_name':    first_name,
                'last_name':     last_name,
                'middle_initial': middle_initial,
                'worker_id':     worker_id,
                'j_ra':          j_ra,
                'classification': 'Unknown',
                'st_hours':      st['hours'],
                'ot_hours':      ot['hours'],
                'dt_hours':      dt['hours'],
                'total_hours':   total_hours,
                'st_rate':       st_rate,
                'ot_rate':       ot_rate,
                'dt_rate':       dt_rate,
                'rate':          st_rate,
                'st_gross':      st['gross'],
                'ot_gross':      ot['gross'],
                'dt_gross':      dt['gross'],
                'gross':         gross_total,
                'deductions':    st['deductions'] + ot['deductions'] + dt['deductions'],
                'net':           st['net'] + ot['net'] + dt['net'],
                'fringe_paid_cash':   0.0,
                'fringe_plan_name':   '',
                'fringe_plan_amount': 0.0,
                'apprentice_program_name': '',
                'apprentice_period': 0,
                'apprentice_percent': 0.0,
            })

    # -------------------------------------------------------------------------
    # Fill in header if not yet extracted
    # -------------------------------------------------------------------------
    if not header:
        header = extract_wh347_header(pdf_path)
    if not compliance_statement:
        compliance_statement = extract_compliance_statement(pdf_path)

    journeymen = sum(1 for w in parsed_rows if w.get('j_ra', '').upper() == 'J')
    apprentices = sum(1 for w in parsed_rows if w.get('j_ra', '').upper() == 'RA')

    return {
        'header':               header,
        'lines':                parsed_rows,
        'totals': {
            'workers':      len(parsed_rows),
            'journeymen':   journeymen,
            'apprentices':  apprentices,
            'total_gross':  round(sum(w.get('gross', 0) for w in parsed_rows), 2),
        },
        'compliance_statement': compliance_statement,
    }
