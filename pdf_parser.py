import pdfplumber
import re
import os
from datetime import datetime


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _safe_float(val):
    try:
        return float(re.sub(r'[\s,]', '', str(val or '')))
    except (ValueError, TypeError):
        return 0.0


def _clean(val):
    if val is None:
        return ''
    return re.sub(r'\s+', ' ', str(val)).strip()


def _blank_header():
    return {
        'contractor_name':           '',
        'contractor_address':        '',
        'payroll_number':            '',
        'week_ending':               '',
        'project_name':              '',
        'project_location':          '',
        'contract_number':           '',
        'wage_determination_number': '',
    }


def _blank_compliance():
    return {
        'certified_signature': False,
        'certified_name':      '',
        'certified_title':     '',
        'certified_date':      '',
        'detected_by_text':    False,
    }


def _blank_worker(row_num=0):
    return {
        'row_number':              row_num,
        'last_name':               '',
        'first_name':              '',
        'middle_initial':          '',
        'worker_id':               '',
        'j_ra':                    '',
        'classification':          '',
        'st_hours':                0.0,
        'ot_hours':                0.0,
        'dt_hours':                0.0,
        'total_hours':             0.0,
        'st_rate':                 0.0,
        'ot_rate':                 0.0,
        'dt_rate':                 0.0,
        'rate':                    0.0,
        'st_gross':                0.0,
        'ot_gross':                0.0,
        'dt_gross':                0.0,
        'gross':                   0.0,
        'fica':                    0.0,
        'withholding':             0.0,
        'deductions':              0.0,
        'net':                     0.0,
        'fringe_paid_cash':        0.0,
        'fringe_plan_name':        '',
        'fringe_plan_amount':      0.0,
        'apprentice_program_name': '',
        'apprentice_period':       0,
        'apprentice_percent':      0.0,
    }


def _finalize_result(header, lines, compliance, parser_used, warnings):
    """Build the standard output dict and run post-parse validation."""
    # Ensure derived fields are consistent
    for w in lines:
        if w['st_rate'] > 0 and w['ot_rate'] == 0:
            w['ot_rate'] = round(w['st_rate'] * 1.5, 2)
        if w['st_rate'] > 0 and w['dt_rate'] == 0:
            w['dt_rate'] = round(w['st_rate'] * 2.0, 2)
        if w['rate'] == 0:
            w['rate'] = w['st_rate']
        # If deductions weren't explicitly set but FICA + withholding were, sum them
        if w['deductions'] == 0 and (w['fica'] + w['withholding']) > 0:
            w['deductions'] = round(w['fica'] + w['withholding'], 2)
        # Recalculate net if it's 0 but gross and deductions are known
        if w['net'] == 0 and w['gross'] > 0:
            w['net'] = round(w['gross'] - w['deductions'], 2)

    # Post-parse validation warnings
    if not lines:
        warnings.append(
            "No worker rows were extracted. The PDF format may not be supported or the file may be image-based (scanned)."
        )
    else:
        zero_gross = sum(1 for w in lines if w['gross'] == 0)
        zero_hours = sum(1 for w in lines if w['total_hours'] == 0)
        if zero_gross > len(lines) * 0.5:
            warnings.append(
                f"{zero_gross}/{len(lines)} workers have $0 gross — pay rate data may not have been extracted."
            )
        if zero_hours:
            warnings.append(
                f"{zero_hours} worker(s) have 0 total hours — hour data may be missing."
            )
        bad_totals = []
        for w in lines:
            computed = round(w['st_hours'] + w['ot_hours'] + w['dt_hours'], 2)
            stated   = w['total_hours']
            if stated > 0 and abs(computed - stated) > 0.5:
                bad_totals.append(w['row_number'])
        if bad_totals:
            warnings.append(
                f"Hour totals don't add up for row(s) {bad_totals[:5]} — ST+OT+DT != total hours."
            )

    journeymen  = sum(1 for w in lines if w.get('j_ra', '').upper() == 'J')
    apprentices = sum(1 for w in lines if w.get('j_ra', '').upper() in ('RA', 'A'))

    return {
        'header':               header or _blank_header(),
        'lines':                lines,
        'totals': {
            'workers':     len(lines),
            'journeymen':  journeymen,
            'apprentices': apprentices,
            'total_gross': round(sum(w.get('gross', 0) for w in lines), 2),
        },
        'compliance_statement': compliance or _blank_compliance(),
        'parser_used':          parser_used,
        'parse_warnings':       warnings,
    }


# ---------------------------------------------------------------------------
# FreeText annotation extractor (Jan 2025 DOL WH-347 form)
# ---------------------------------------------------------------------------

def _get_freetext_annotations(pdf_path):
    from pdfminer.pdfdocument import PDFDocument
    from pdfminer.pdfparser  import PDFParser
    from pdfminer.pdftypes   import resolve1
    from pdfminer.pdfpage    import PDFPage

    def decode(v):
        if isinstance(v, bytes):
            return v.decode('utf-8', errors='replace')
        return str(v) if v is not None else ''

    annotations = []
    with open(pdf_path, 'rb') as f:
        parser = PDFParser(f)
        doc    = PDFDocument(parser)
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
                if 'FreeText' not in decode(annot.get('Subtype', '')):
                    continue
                contents = decode(annot.get('Contents', '')).strip()
                if not contents:
                    continue
                rect = annot.get('Rect', [0, 0, 0, 0])
                try:
                    x0, y0, x1, y1 = [float(v) for v in rect]
                except (TypeError, ValueError):
                    continue
                annotations.append({'page': page_num, 'x0': x0, 'y0': y0,
                                     'x1': x1, 'y1': y1, 'content': contents})
    return annotations


# X-coordinate column ranges for Jan 2025 DOL WH-347 form
_WORKER_COL_RANGES = {
    'row_number':       (0,    66),
    'last_name':        (66,   118),
    'first_name':       (118,  165),
    'middle_initial':   (165,  193),
    'worker_id':        (193,  228),
    'j_ra':             (228,  260),
    'classification':   (260,  341),
    'ot_hours_sub':     (395,  435),  # OT sub-row hours
    'dt_hours_sub':     (450,  480),  # DT sub-row hours (if present)
    'total_hours':      (430,  450),  # total hours (non-overlapping with dt_hours_sub)
    'st_rate':          (462,  503),
    'fringe_credit':    (503,  535),
    'gross':            (597,  637),
    'fica':             (637,  666),
    'withholding':      (666,  697),
    'total_deductions': (697,  727),
    'net':              (727,  800),
}

_TOTAL_HOURS_RANGE = (430, 450)


def _x_to_col(x0):
    for col, (lo, hi) in _WORKER_COL_RANGES.items():
        if lo <= x0 < hi:
            return col
    return None


def _extract_header_from_annotations(annots, page_num=1):
    """Single-pass header extractor using two y-bands (upper/lower)."""
    header = _blank_header()
    page_annots = [a for a in annots if a['page'] == page_num and a['y0'] > 350]

    if not page_annots:
        # Fallback: top 40pt of whatever is on the page
        page_annots = [a for a in annots if a['page'] == page_num]
        if page_annots:
            max_y = max(a['y0'] for a in page_annots)
            page_annots = [a for a in page_annots if a['y0'] >= max_y - 40]

    if not page_annots:
        return header

    # Split into two bands by the median y value
    ys = sorted({a['y0'] for a in page_annots}, reverse=True)
    if len(ys) >= 2:
        mid_y = ys[len(ys) // 2]
    else:
        mid_y = ys[0] - 1  # everything is upper

    upper = [a for a in page_annots if a['y0'] >= mid_y]
    lower = [a for a in page_annots if a['y0'] <  mid_y]

    def assign_band(annots_band, is_upper):
        for a in annots_band:
            x0, val = a['x0'], a['content']
            if x0 < 200:
                key = 'project_name' if is_upper else 'project_location'
            elif 200 <= x0 < 342:
                key = 'contract_number' if is_upper else 'wage_determination_number'
            elif 342 <= x0 < 444:
                if is_upper:
                    key = 'payroll_number'
                else:
                    key = 'week_ending' if re.search(r'\d{1,2}[/\-]\d{1,2}[/\-]\d{2,4}', val) else 'payroll_number'
            else:
                key = 'contractor_name' if is_upper else 'contractor_address'
            if not header.get(key):
                header[key] = val.strip()

    assign_band(upper, is_upper=True)
    assign_band(lower, is_upper=False)
    return header


def _extract_compliance_from_annotations(annots, total_pages):
    result = _blank_compliance()
    page_annots = [a for a in annots if a['page'] == total_pages] or \
                  [a for a in annots if a['page'] > 1]
    if not page_annots:
        return result

    # Bottom 6 annotations = signature block
    for a in sorted(page_annots, key=lambda x: x['y0'])[:6]:
        val = a['content']
        if re.search(r'\d{1,2}[/\-]\d{1,2}[/\-]\d{2,4}', val):
            result['certified_date']      = val.strip()
            result['certified_signature'] = True
            result['detected_by_text']    = True
        elif '@' not in val and not re.search(r'\(\d{3}\)', val):
            if not result['certified_name'] and len(val) > 2:
                result['certified_name']      = val.strip()
                result['certified_signature'] = True
                result['detected_by_text']    = True

    # Mid-page: "Name, Title" style certifying official
    for a in sorted([a for a in page_annots if a['y0'] > 50], key=lambda x: -x['y0'])[:4]:
        val = a['content']
        if a['x0'] > 400 and ',' in val and not result['certified_title']:
            parts = val.split(',', 1)
            if len(parts) == 2:
                result['certified_name']  = parts[0].strip()
                result['certified_title'] = parts[1].strip()
                result['certified_signature'] = True
                result['detected_by_text']    = True
    return result


def _extract_workers_from_annotations(annots, page_num=1):
    page_annots = [a for a in annots if a['page'] == page_num]
    row_markers = [a for a in page_annots
                   if a['x0'] < 66 and re.match(r'^\d+$', a['content'].strip())]
    if not row_markers:
        return []

    workers = []
    for marker in row_markers:
        row_y0   = marker['y0']
        row_y1   = marker['y1']
        band_lo  = row_y0 - 5
        band_hi  = row_y1 + 5

        row_annots = [a for a in page_annots
                      if a['y0'] >= band_lo and a['y1'] <= band_hi + 10]

        w = _blank_worker(int(marker['content'].strip()))

        for a in row_annots:
            col = _x_to_col(a['x0'])
            if col is None:
                continue
            val = a['content'].strip()

            if   col == 'last_name':        w['last_name']       = val.title()
            elif col == 'first_name':       w['first_name']      = val.title()
            elif col == 'middle_initial':   w['middle_initial']  = val
            elif col == 'worker_id':        w['worker_id']       = val
            elif col == 'j_ra':             w['j_ra']            = val.upper()
            elif col == 'classification':   w['classification']  = val
            elif col == 'ot_hours_sub':     w['ot_hours']        = _safe_float(val)
            elif col == 'dt_hours_sub':     w['dt_hours']        = _safe_float(val)
            elif col == 'total_hours':      w['total_hours']     = _safe_float(val)
            elif col == 'st_rate':
                w['st_rate'] = _safe_float(val)
                w['rate']    = w['st_rate']
            elif col == 'fringe_credit':    w['fringe_paid_cash']= _safe_float(val)
            elif col == 'gross':            w['gross']           = _safe_float(val)
            elif col == 'fica':             w['fica']            = _safe_float(val)
            elif col == 'withholding':      w['withholding']     = _safe_float(val)
            elif col == 'total_deductions': w['deductions']      = _safe_float(val)
            elif col == 'net':              w['net']             = _safe_float(val)

        # Derive ST hours
        w['st_hours'] = max(round(w['total_hours'] - w['ot_hours'] - w['dt_hours'], 2), 0.0)

        # Gross components
        if w['st_rate'] > 0:
            w['ot_rate']  = round(w['st_rate'] * 1.5, 2)
            w['dt_rate']  = round(w['st_rate'] * 2.0, 2)
            w['st_gross'] = round(w['st_hours'] * w['st_rate'],  2)
            w['ot_gross'] = round(w['ot_hours'] * w['ot_rate'],  2)
            w['dt_gross'] = round(w['dt_hours'] * w['dt_rate'],  2)

        workers.append(w)
    return workers


# ---------------------------------------------------------------------------
# iTextSharp multi-page WH-347 format (27-col / 26-col with ST/OT/DT sub-rows)
# ---------------------------------------------------------------------------

def _is_itextsharp_format(pdf_path):
    with pdfplumber.open(pdf_path) as pdf:
        if not pdf.pages:
            return False
        tables = pdf.pages[0].extract_tables()
        if not tables or not tables[0] or not tables[0][0]:
            return False
        num_cols  = len(tables[0][0])
        first_row = ' '.join(_clean(c) for c in tables[0][0] if c).upper()
        return num_cols >= 26 and ('PROJECT NAME' in first_row or 'CONTRACT NO' in first_row)


def _extract_itextsharp_data(pdf_path):
    header     = _blank_header()
    compliance = _blank_compliance()
    warnings   = []
    all_workers    = {}
    last_row_num   = 0
    header_extracted = False

    with pdfplumber.open(pdf_path) as pdf:
        for page_num, page in enumerate(pdf.pages, 1):
            tables = page.extract_tables()
            if not tables:
                continue
            table = tables[0]
            if not table:
                continue

            for row_idx, row in enumerate(table):
                if not row:
                    continue
                row_len = len(row)
                cell0   = _clean(row[0])

                # Header row
                if not header_extracted and row_len >= 26 and (
                        'PROJECT NAME' in cell0.upper() or 'CONTRACT NO' in cell0.upper()):
                    if row_idx + 1 < len(table):
                        v1 = table[row_idx + 1]
                        header['project_name']    = _clean(v1[0])  if len(v1) > 0  else ''
                        header['contract_number'] = _clean(v1[5])  if len(v1) > 5  else ''
                        header['payroll_number']  = _clean(v1[9])  if len(v1) > 9  else ''
                        header['contractor_name'] = _clean(v1[16]) if len(v1) > 16 else ''
                    if row_idx + 3 < len(table):
                        v3 = table[row_idx + 3]
                        header['project_location']          = _clean(v3[0])  if len(v3) > 0  else ''
                        header['wage_determination_number'] = _clean(v3[5])  if len(v3) > 5  else ''
                        header['week_ending']               = _clean(v3[9])  if len(v3) > 9  else ''
                        header['contractor_address']        = _clean(v3[16]) if len(v3) > 16 else ''
                    header_extracted = True
                    continue

                # Signature block
                if 'SIGNATURE OF CERTIFYING OFFICIAL' in cell0.upper() and row_idx + 1 < len(table):
                    sig = table[row_idx + 1]
                    name_val = _clean(sig[0]) if sig else ''
                    date_val = _clean(sig[2]) if len(sig) > 2 else ''
                    if name_val:
                        compliance['certified_name'] = name_val
                    if re.search(r'\d{1,2}[/\-]\d{1,2}[/\-]\d{2,4}', date_val):
                        compliance['certified_date']      = date_val
                        compliance['certified_signature'] = True
                        compliance['detected_by_text']    = True
                    continue

                # Certifying official name/title
                if not compliance['certified_title']:
                    for ci, cv in enumerate(row):
                        if cv and 'CERTIFYING OFFICIAL' in str(cv).upper():
                            if row_idx + 1 < len(table) and ci < len(table[row_idx + 1]):
                                nt = _clean(table[row_idx + 1][ci])
                                if nt and '/' in nt:
                                    parts = [p.strip() for p in nt.split('/')]
                                    if len(parts) >= 2:
                                        compliance['certified_name']  = compliance['certified_name'] or parts[0]
                                        compliance['certified_title'] = parts[1]
                            break

                # Column offsets by row width
                if row_len >= 27:
                    j_ra_col=6; cls_col=7; type_col=8; day_start=9; day_end=16
                    total_h=16; rate_c=17; fringe_c=18; week_g=20; cumul_g=21
                    withhold=22; fica_c=23; other_d=24; total_d=25; net_c=26
                elif row_len >= 26:
                    j_ra_col=5; cls_col=6; type_col=7; day_start=8; day_end=15
                    total_h=15; rate_c=16; fringe_c=17; week_g=19; cumul_g=20
                    withhold=21; fica_c=22; other_d=23; total_d=24; net_c=25
                else:
                    continue

                row_type   = _clean(row[type_col]).upper() if type_col < row_len else ''
                is_primary = bool(cell0 and cell0.isdigit())

                if not is_primary and row_type not in ('ST', 'OT', 'DT'):
                    continue

                if is_primary:
                    last_row_num = int(cell0)
                if last_row_num == 0:
                    continue
                rn = last_row_num

                daily_hours = sum(_safe_float(row[i]) for i in range(day_start, day_end) if i < row_len)
                rate        = _safe_float(row[rate_c]) if rate_c < row_len else 0.0

                if rn not in all_workers:
                    all_workers[rn] = _blank_worker(rn)

                w = all_workers[rn]

                if is_primary:
                    w['last_name']      = _clean(row[1]).title()
                    w['first_name']     = _clean(row[2]).title()
                    w['middle_initial'] = _clean(row[3])
                    w['worker_id']      = _clean(row[4])
                    w['j_ra']           = _clean(row[j_ra_col]).upper()
                    w['classification'] = _clean(row[cls_col])
                    w['total_hours']    = _safe_float(row[total_h])  if total_h  < row_len else 0.0
                    w['gross']          = _safe_float(row[week_g])   if week_g   < row_len else 0.0
                    w['fringe_paid_cash']= _safe_float(row[fringe_c]) if fringe_c < row_len else 0.0
                    w['withholding']    = _safe_float(row[withhold]) if withhold < row_len else 0.0
                    w['fica']           = _safe_float(row[fica_c])   if fica_c   < row_len else 0.0
                    w['deductions']     = _safe_float(row[total_d])  if total_d  < row_len else 0.0
                    w['net']            = _safe_float(row[net_c])    if net_c    < row_len else 0.0

                if   row_type == 'ST':
                    w['st_hours'] = daily_hours; w['st_rate'] = rate; w['rate'] = rate
                    w['st_gross'] = round(daily_hours * rate, 2)
                elif row_type == 'OT':
                    w['ot_hours'] = daily_hours; w['ot_rate'] = rate
                    w['ot_gross'] = round(daily_hours * rate, 2)
                elif row_type == 'DT':
                    w['dt_hours'] = daily_hours; w['dt_rate'] = rate
                    w['dt_gross'] = round(daily_hours * rate, 2)

    if compliance['certified_name'] and not compliance['certified_date']:
        compliance['certified_signature'] = True
        compliance['detected_by_text']    = True

    rows = [all_workers[k] for k in sorted(all_workers)]
    return _finalize_result(header, rows, compliance, 'itextsharp', warnings)


# ---------------------------------------------------------------------------
# Simple 10-column custom WH-347 format
# ---------------------------------------------------------------------------

def _is_simple10_format(pdf_path):
    with pdfplumber.open(pdf_path) as pdf:
        if not pdf.pages:
            return False
        tables = pdf.pages[0].extract_tables()
        if len(tables) < 2:
            return False
        t0 = tables[0]
        if not t0 or not t0[0] or len(t0[0]) != 2:
            return False
        if ':' not in str(t0[0][0] or ''):
            return False
        t1 = tables[1]
        return bool(t1 and t1[0] and len(t1[0]) == 10)


def _extract_simple10_data(pdf_path):
    header     = _blank_header()
    compliance = _blank_compliance()
    warnings   = []

    LABEL_MAP = {
        'project name':          'project_name',
        'project no':            'contract_number',
        'contract no':           'contract_number',
        'certified payroll no':  'payroll_number',
        'payroll no':            'payroll_number',
        'prime contractor':      'contractor_name',
        'contractor':            'contractor_name',
        'project location':      'project_location',
        'location':              'project_location',
        'wage determination no': 'wage_determination_number',
        'wage det no':           'wage_determination_number',
        'week ending date':      'week_ending',
        'week ending':           'week_ending',
        'address':               'contractor_address',
    }

    parsed_rows = []

    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            for table in page.extract_tables() or []:
                if not table or not table[0]:
                    continue
                num_cols = len(table[0])

                if num_cols == 2:
                    for row in table:
                        if not row or len(row) < 2:
                            continue
                        label = _clean(row[0]).rstrip(':').lower()
                        value = _clean(row[1])
                        if not value:
                            continue
                        for key, field in LABEL_MAP.items():
                            if label.startswith(key):
                                if not header[field]:
                                    header[field] = value
                                break
                        if label.startswith('certifying official'):
                            for sep in ['–', '—', '/', ',']:
                                if sep in value:
                                    parts = [p.strip() for p in value.split(sep, 1)]
                                    compliance['certified_name']  = parts[0]
                                    compliance['certified_title'] = parts[1] if len(parts) > 1 else ''
                                    break
                            else:
                                compliance['certified_name'] = value
                            compliance['certified_signature'] = True
                            compliance['detected_by_text']    = True
                        elif label == 'date' and re.search(r'\d{1,2}[/\-]\d{1,2}[/\-]\d{2,4}', value):
                            compliance['certified_date']      = value
                            compliance['certified_signature'] = True
                            compliance['detected_by_text']    = True

                elif num_cols == 10:
                    for row in table:
                        if not row:
                            continue
                        cell0 = _clean(row[0])
                        if not cell0.isdigit():
                            continue

                        full_name = _clean(row[1])
                        if ',' in full_name:
                            parts      = full_name.split(',', 1)
                            last_name  = parts[0].strip().title()
                            first_name = parts[1].strip().title()
                        else:
                            nm         = full_name.split()
                            last_name  = nm[-1].title()  if nm else ''
                            first_name = ' '.join(nm[:-1]).title() if len(nm) > 1 else ''

                        classification = _clean(row[2])
                        st_hours  = _safe_float(row[3])
                        ot_hours  = _safe_float(row[4])
                        total_h   = _safe_float(row[5])
                        st_rate   = _safe_float(row[6])
                        gross     = _safe_float(row[7])
                        deductions= _safe_float(row[8])
                        net       = _safe_float(row[9])

                        ot_rate  = round(st_rate * 1.5, 2)
                        dt_rate  = round(st_rate * 2.0, 2)
                        dt_hours = round(max(total_h - st_hours - ot_hours, 0.0), 2)
                        ot_gross = round(ot_hours * ot_rate, 2)
                        dt_gross = round(dt_hours * dt_rate, 2)
                        st_gross = round(max(gross - ot_gross - dt_gross, 0.0), 2)

                        cls_upper = classification.upper()
                        j_ra = 'RA' if ('APPRENTICE' in cls_upper or '(RA)' in cls_upper) else 'J'

                        w = _blank_worker(int(cell0))
                        w.update({
                            'last_name': last_name, 'first_name': first_name,
                            'j_ra': j_ra, 'classification': classification,
                            'st_hours': st_hours, 'ot_hours': ot_hours, 'dt_hours': dt_hours,
                            'total_hours': total_h,
                            'st_rate': st_rate, 'ot_rate': ot_rate, 'dt_rate': dt_rate,
                            'rate': st_rate,
                            'st_gross': st_gross, 'ot_gross': ot_gross, 'dt_gross': dt_gross,
                            'gross': gross, 'deductions': deductions, 'net': net,
                        })
                        parsed_rows.append(w)

    return _finalize_result(header, parsed_rows, compliance, 'simple10', warnings)


# ---------------------------------------------------------------------------
# Generic table fallback — flexible column count, common WH-347 layouts
# ---------------------------------------------------------------------------

def _extract_generic_table_data(pdf_path):
    """
    Flexible fallback for any tabular WH-347 PDF.
    Tries to locate worker rows by: numeric first cell OR "Last, First" name in cell 0-1.
    Handles 8–27 column layouts.
    """
    header     = _blank_header()
    compliance = _blank_compliance()
    warnings   = []
    parsed_rows = []
    seen_rows   = set()

    # Try text-based header extraction
    try:
        header = _extract_header_text(pdf_path)
    except Exception:
        pass

    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            for table in page.extract_tables() or []:
                if not table:
                    continue

                # Detect header row to find column mapping
                col_map = _detect_column_map(table)

                for row in table:
                    if not row:
                        continue
                    cleaned = [_clean(c) for c in row]
                    n = len(cleaned)
                    if n < 5:
                        continue

                    # Locate the row number: try col 0, or if "Last, First" is col 0 try col 1
                    row_num = None
                    name_col_offset = 0
                    if cleaned[0].isdigit():
                        row_num = int(cleaned[0])
                    elif n > 1 and cleaned[1].isdigit():
                        row_num = int(cleaned[1])
                        name_col_offset = 1

                    if row_num is None or row_num in seen_rows:
                        continue
                    seen_rows.add(row_num)

                    # Extract using detected column map or positional fallback
                    w = _blank_worker(row_num)
                    _fill_worker_from_row(w, cleaned, col_map, name_col_offset, n)
                    parsed_rows.append(w)

    # Try compliance from last page text
    try:
        compliance = extract_compliance_statement(pdf_path)
    except Exception:
        pass

    return _finalize_result(header, parsed_rows, compliance, 'generic_table', warnings)


def _detect_column_map(table):
    """
    Scan the first few rows of a table for header keywords.
    Returns a dict mapping field names to column indexes.
    """
    col_map = {}
    HEADER_KEYWORDS = {
        'row_number':    r'^#$|^no\.?$|^row',
        'last_name':     r'last\s*name|surname',
        'first_name':    r'first\s*name',
        'classification':r'class|trade|occupation',
        'j_ra':          r'^j/ra$|journeyman|apprentice\s*status',
        'st_hours':      r'^st\s*hr|straight.*hour|reg.*hour',
        'ot_hours':      r'^ot\s*hr|over.*hour',
        'dt_hours':      r'^dt\s*hr|double.*hour',
        'total_hours':   r'total\s*hr|total\s*hours',
        'st_rate':       r'st\s*rate|straight.*rate|base\s*rate|hourly\s*rate',
        'ot_rate':       r'ot\s*rate|over.*rate',
        'gross':         r'gross\s*(pay|wages|amount)?$|total\s*gross',
        'deductions':    r'deduct|total\s*ded',
        'net':           r'^net\s*(pay|wages)?$',
    }
    for row in table[:6]:
        if not row:
            continue
        for ci, cell in enumerate(row):
            cell_str = _clean(cell).lower()
            if not cell_str:
                continue
            for field, pattern in HEADER_KEYWORDS.items():
                if re.search(pattern, cell_str) and field not in col_map:
                    col_map[field] = ci
    return col_map


def _fill_worker_from_row(w, cleaned, col_map, offset, n):
    """Fill a worker dict from a cleaned row using col_map or positional fallback."""
    def get(field, fallback_idx):
        idx = col_map.get(field, fallback_idx + offset)
        return cleaned[idx] if 0 <= idx < n else ''

    # Name: handle "Last, First" or separate columns
    last_col  = col_map.get('last_name',  1 + offset)
    first_col = col_map.get('first_name', 2 + offset)
    if last_col < n:
        name_val = cleaned[last_col]
        if ',' in name_val and first_col >= n:
            parts = name_val.split(',', 1)
            w['last_name']  = parts[0].strip().title()
            w['first_name'] = parts[1].strip().title()
        else:
            w['last_name']  = name_val.title()
            if first_col < n:
                w['first_name'] = cleaned[first_col].title()

    mi_col  = col_map.get('middle_initial', 3 + offset)
    id_col  = col_map.get('worker_id',      4 + offset)
    jra_col = col_map.get('j_ra',           5 + offset)
    cls_col = col_map.get('classification', 6 + offset)
    if mi_col  < n: w['middle_initial']  = cleaned[mi_col]
    if id_col  < n: w['worker_id']       = cleaned[id_col]
    if jra_col < n: w['j_ra']            = cleaned[jra_col].upper()
    if cls_col < n: w['classification']  = cleaned[cls_col]

    # Infer J/RA from classification if not set
    if not w['j_ra']:
        cls_up = w['classification'].upper()
        w['j_ra'] = 'RA' if ('APPRENTICE' in cls_up or '(RA)' in cls_up) else 'J'

    # Hours / rates / pay — positional fallback based on common WH-347 column order
    if 'st_hours' in col_map:
        w['st_hours']    = _safe_float(cleaned[col_map['st_hours']])
        w['ot_hours']    = _safe_float(cleaned[col_map.get('ot_hours', -1)]) if 'ot_hours' in col_map else 0.0
        w['dt_hours']    = _safe_float(cleaned[col_map.get('dt_hours', -1)]) if 'dt_hours' in col_map else 0.0
        w['total_hours'] = _safe_float(cleaned[col_map.get('total_hours', -1)]) if 'total_hours' in col_map else 0.0
        w['st_rate']     = _safe_float(cleaned[col_map.get('st_rate', -1)]) if 'st_rate' in col_map else 0.0
        w['gross']       = _safe_float(cleaned[col_map.get('gross', -1)]) if 'gross' in col_map else 0.0
        w['deductions']  = _safe_float(cleaned[col_map.get('deductions', -1)]) if 'deductions' in col_map else 0.0
        w['net']         = _safe_float(cleaned[col_map.get('net', -1)]) if 'net' in col_map else 0.0
    else:
        # Pure positional — works for 14-20 col WH-347 variants
        base = 7 + offset
        if n >= base + 8:
            w['st_hours'] = _safe_float(cleaned[base])
            w['ot_hours'] = _safe_float(cleaned[base + 1])
            w['dt_hours'] = _safe_float(cleaned[base + 2])
            w['total_hours'] = _safe_float(cleaned[base + 3])
            w['st_rate']  = _safe_float(cleaned[base + 4])
            w['gross']    = _safe_float(cleaned[base + 5])
            w['deductions'] = _safe_float(cleaned[base + 6])
            w['net']      = _safe_float(cleaned[base + 7])
        elif n >= base + 4:
            w['total_hours'] = _safe_float(cleaned[base])
            w['st_rate']     = _safe_float(cleaned[base + 1])
            w['gross']       = _safe_float(cleaned[base + 2])
            w['net']         = _safe_float(cleaned[base + 3])

    if w['total_hours'] == 0:
        w['total_hours'] = round(w['st_hours'] + w['ot_hours'] + w['dt_hours'], 2)
    if w['st_hours'] == 0 and w['total_hours'] > 0 and w['ot_hours'] == 0:
        w['st_hours'] = w['total_hours']


# ---------------------------------------------------------------------------
# Text-based header and compliance fallbacks
# ---------------------------------------------------------------------------

def _extract_header_text(pdf_path):
    """Extract header fields from raw text using regex (fallback for non-annotation PDFs)."""
    header = _blank_header()
    with pdfplumber.open(pdf_path) as pdf:
        if not pdf.pages:
            return header
        text = (pdf.pages[0].extract_text() or '')
        if len(pdf.pages) > 1:
            text += '\n' + (pdf.pages[1].extract_text() or '')

    def find(pattern, default=''):
        m = re.search(pattern, text, re.IGNORECASE)
        return m.group(1).strip() if m else default

    header['contractor_name']  = find(r'Contractor[:\s]+([A-Za-z0-9\s&,\.\-\']{3,60}?)(?:\n|Address|LLC|Inc|$)')
    header['contractor_address']= find(r'Address[:\s]+([^\n]{5,80})')
    header['payroll_number']   = find(r'Payroll\s*(?:No\.?|Number|#)[:\s]*(\d+)')
    header['week_ending']      = find(r'Week\s*Ending[:\s]+(\d{1,2}[/\-]\d{1,2}[/\-]\d{2,4})')
    header['project_name']     = find(r'Project\s*(?:Name|and\s*Location)?[:\s]+([^\n]{3,80})')
    header['contract_number']  = find(r'Contract\s*(?:No\.?|Number|#)[:\s]+([A-Z0-9\-]{3,30})')
    header['wage_determination_number'] = find(r'Wage\s*Det(?:ermination)?[:\s#.]*([A-Z]{2}\d{6,})')
    return header


def extract_compliance_statement(pdf_path):
    result = _blank_compliance()
    with pdfplumber.open(pdf_path) as pdf:
        if not pdf.pages:
            return result
        text = (pdf.pages[-1].extract_text() or '')
        if len(pdf.pages) == 1:
            text = (pdf.pages[0].extract_text() or '')

    cert_kws = ['certify', 'penalties of perjury', 'statement of compliance',
                'willful falsification', 'i, the undersigned']
    if not any(kw in text.lower() for kw in cert_kws):
        return result

    result['detected_by_text'] = True
    name_m = re.search(
        r'(?:Signature|Signed|Name)[:\s]+([A-Za-z\s\.\-\']{3,50}?)(?:\n|Title|Date)',
        text, re.IGNORECASE)
    date_m = re.search(r'Date[:\s]+(\d{1,2}[/\-]\d{1,2}[/\-]\d{2,4})', text, re.IGNORECASE)

    if name_m:
        result['certified_name']      = name_m.group(1).strip()
        result['certified_signature'] = True
    if date_m:
        result['certified_date']      = date_m.group(1).strip()
        result['certified_signature'] = True
    return result


# ---------------------------------------------------------------------------
# Text-line fallback (last resort — scanned or unusual layout PDFs)
# ---------------------------------------------------------------------------

def _extract_text_fallback(pdf_path):
    warnings   = []
    header     = _blank_header()
    compliance = _blank_compliance()
    parsed_rows = []

    warnings.append("Fell back to text-line parser — data quality may be limited.")

    lines = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ''
            for raw in text.splitlines():
                ln = re.sub(r'\s+', ' ', raw.strip())
                if ln:
                    lines.append(ln)

    name_pattern = re.compile(
        r'^(\d+)\s+([A-Z\-\']+)\s+([A-Z\-\']+)\s*([A-Z]?)\s+([A-Z0-9]{3,})\s+(J|RA)'
    )

    blocks   = []
    current  = []
    for line in lines:
        if re.match(r'^\d+\s+[A-Z]', line):
            if current:
                blocks.append(current)
            current = [line]
        elif current:
            current.append(line)
    if current:
        blocks.append(current)

    for block in blocks:
        m = name_pattern.match(block[0])
        if not m:
            continue
        w = _blank_worker(int(m.group(1)))
        w['last_name']      = m.group(2).title()
        w['first_name']     = m.group(3).title()
        w['middle_initial'] = m.group(4)
        w['worker_id']      = m.group(5)
        w['j_ra']           = m.group(6)

        for line in block:
            tm = re.search(r'\b(ST|OT|DT)\b', line)
            if not tm:
                continue
            nums = [_safe_float(n) for n in re.findall(r'\d+\.\d+', line)]
            if len(nums) < 5:
                continue
            record = {'hours': nums[-5], 'rate': nums[-4], 'gross': nums[-3],
                      'deductions': nums[-2], 'net': nums[-1]}
            t = tm.group(1)
            if   t == 'ST': w['st_hours']=record['hours']; w['st_rate']=record['rate']; w['st_gross']=record['gross']
            elif t == 'OT': w['ot_hours']=record['hours']; w['ot_rate']=record['rate']; w['ot_gross']=record['gross']
            elif t == 'DT': w['dt_hours']=record['hours']; w['dt_rate']=record['rate']; w['dt_gross']=record['gross']

        w['total_hours'] = round(w['st_hours'] + w['ot_hours'] + w['dt_hours'], 2)
        w['gross']       = round(w['st_gross'] + w['ot_gross'] + w['dt_gross'], 2)
        parsed_rows.append(w)

    try:
        header     = _extract_header_text(pdf_path)
        compliance = extract_compliance_statement(pdf_path)
    except Exception:
        pass

    return _finalize_result(header, parsed_rows, compliance, 'text_fallback', warnings)


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def extract_wh347_data(pdf_path):
    """
    Extract WH-347 payroll data from a PDF.

    Tries parsers in confidence order:
      1. iTextSharp (27-col/26-col ST/OT/DT sub-rows)
      2. Simple 10-column key-value format
      3. Jan 2025 DOL FreeText annotation format
      4. Generic flexible table parser
      5. Text-line fallback

    Returns dict with keys: header, lines, totals, compliance_statement,
                             parser_used, parse_warnings
    """
    if not os.path.exists(pdf_path):
        raise FileNotFoundError(f'File not found: {pdf_path}')

    # 1 — iTextSharp
    try:
        if _is_itextsharp_format(pdf_path):
            print('[parser] iTextSharp format detected')
            result = _extract_itextsharp_data(pdf_path)
            if result['totals']['workers'] > 0:
                return result
    except Exception as e:
        print(f'[parser] iTextSharp error: {e}')

    # 2 — Simple 10-col
    try:
        if _is_simple10_format(pdf_path):
            print('[parser] Simple 10-col format detected')
            result = _extract_simple10_data(pdf_path)
            if result['totals']['workers'] > 0:
                return result
    except Exception as e:
        print(f'[parser] Simple 10-col error: {e}')

    # 3 — FreeText annotations (Jan 2025 DOL form)
    try:
        annots = _get_freetext_annotations(pdf_path)
        if annots:
            print(f'[parser] FreeText annotations found ({len(annots)} total)')
            with pdfplumber.open(pdf_path) as pdf:
                total_pages = len(pdf.pages)

            header     = _extract_header_from_annotations(annots, page_num=1)
            compliance = _extract_compliance_from_annotations(annots, total_pages)

            worker_pages = range(1, total_pages + 1) if total_pages == 1 else range(1, total_pages)
            rows = []
            for pg in worker_pages:
                rows.extend(_extract_workers_from_annotations(annots, page_num=pg))

            if rows:
                return _finalize_result(header, rows, compliance, 'freetext_annotation', [])
            print('[parser] FreeText annotations found but no worker rows — trying table parser')
    except Exception as e:
        print(f'[parser] FreeText annotation error: {e}')

    # 4 — Generic flexible table
    try:
        print('[parser] Trying generic table parser')
        result = _extract_generic_table_data(pdf_path)
        if result['totals']['workers'] > 0:
            return result
    except Exception as e:
        print(f'[parser] Generic table error: {e}')

    # 5 — Text-line fallback
    print('[parser] All structured parsers failed — using text-line fallback')
    return _extract_text_fallback(pdf_path)
