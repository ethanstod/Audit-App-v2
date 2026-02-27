import pdfplumber
import re
import os


def extract_wh347_data(pdf_path):
    """
    Robust table-based WH-347 parser.

    Strategy:
    1. Attempt structured table extraction.
    2. If no valid tables found, fallback to text-based anchored parsing.
    3. Return standardized structure used by audits + report.

    Returns:
    {
        "lines": [...],
        "totals": {"workers": int}
    }
    """

    if not os.path.exists(pdf_path):
        raise FileNotFoundError(f"File not found: {pdf_path}")

    def clean_cell(cell):
        if not cell:
            return ""
        return str(cell).strip()

    def safe_float(val):
        try:
            val = str(val).replace(",", "")
            val = re.sub(r"[^\d\.]", "", val)
            return float(val or 0)
        except:
            return 0.0

    parsed_rows = []

    with pdfplumber.open(pdf_path) as pdf:
        for page_number, page in enumerate(pdf.pages, start=1):

            tables = page.extract_tables()

            # -----------------------------------------------------
            # TABLE MODE
            # -----------------------------------------------------
            for table in tables:
                if not table:
                    continue

                for row in table:
                    if not row:
                        continue

                    cleaned = [clean_cell(c) for c in row]

                    # Worker rows begin with numeric entry number
                    if not cleaned[0].isdigit():
                        continue

                    try:
                        row_number = int(cleaned[0])
                        last_name = cleaned[1].title()
                        first_name = cleaned[2].title()
                        middle_initial = cleaned[3]
                        worker_id = cleaned[4]
                        j_ra = cleaned[5]
                        classification = cleaned[6]

                        st_hours = safe_float(cleaned[7])
                        ot_hours = safe_float(cleaned[8])
                        dt_hours = safe_float(cleaned[9])
                        total_hours = safe_float(cleaned[10])

                        rate = safe_float(cleaned[11])
                        gross = safe_float(cleaned[12])
                        deductions = safe_float(cleaned[13])
                        net = safe_float(cleaned[14])

                    except Exception:
                        continue

                    parsed_rows.append({
                        "row_number": row_number,
                        "first_name": first_name,
                        "last_name": last_name,
                        "middle_initial": middle_initial,
                        "worker_id": worker_id,
                        "j_ra": j_ra,
                        "classification": classification,
                        "st_hours": st_hours,
                        "ot_hours": ot_hours,
                        "dt_hours": dt_hours,
                        "total_hours": total_hours,
                        "rate": rate,
                        "gross": gross,
                        "deductions": deductions,
                        "net": net,
                    })

    # ---------------------------------------------------------
    # FALLBACK TEXT MODE (if table extraction fails)
    # ---------------------------------------------------------
    if not parsed_rows:

        print("⚠️ No structured tables found — using fallback text parser.")

        lines = []

        with pdfplumber.open(pdf_path) as pdf:
            for page in pdf.pages:
                text = page.extract_text() or ""
                for raw in text.splitlines():
                    cleaned = re.sub(r"\s+", " ", raw.strip())
                    if cleaned:
                        lines.append(cleaned)

        worker_blocks = []
        current = []

        for line in lines:
            if re.match(r"^\d+\s+[A-Z]", line):
                if current:
                    worker_blocks.append(current)
                current = [line]
            else:
                if current:
                    current.append(line)

        if current:
            worker_blocks.append(current)

        name_pattern = re.compile(
            r"^(\d+)\s+([A-Z\-']+)\s+([A-Z\-']+)\s*([A-Z]?)\s+([A-Z0-9]{3,})\s+(J|RA)"
        )

        for block in worker_blocks:
            match = name_pattern.match(block[0])
            if not match:
                continue

            row_number = int(match.group(1))
            last_name = match.group(2).title()
            first_name = match.group(3).title()
            middle_initial = match.group(4) if match.group(4) else ""
            worker_id = match.group(5)
            j_ra = match.group(6)

            st = {"hours": 0, "rate": 0, "gross": 0, "deductions": 0, "net": 0}
            ot = {"hours": 0, "rate": 0, "gross": 0, "deductions": 0, "net": 0}
            dt = {"hours": 0, "rate": 0, "gross": 0, "deductions": 0, "net": 0}

            for line in block:
                type_match = re.search(r"\b(ST|OT|DT)\b", line)
                if not type_match:
                    continue

                nums = re.findall(r"\d+\.\d+", line)
                if len(nums) < 5:
                    continue

                nums = [safe_float(n) for n in nums]

                net = nums[-1]
                deductions = nums[-2]
                gross = nums[-3]
                rate = nums[-4]
                hours = nums[-5]

                record = {
                    "hours": hours,
                    "rate": rate,
                    "gross": gross,
                    "deductions": deductions,
                    "net": net,
                }

                if type_match.group(1) == "ST":
                    st = record
                elif type_match.group(1) == "OT":
                    ot = record
                elif type_match.group(1) == "DT":
                    dt = record

            total_hours = st["hours"] + ot["hours"] + dt["hours"]
            gross_total = st["gross"] + ot["gross"] + dt["gross"]
            deductions_total = (
                st["deductions"] + ot["deductions"] + dt["deductions"]
            )
            net_total = st["net"] + ot["net"] + dt["net"]

            parsed_rows.append({
                "row_number": row_number,
                "first_name": first_name,
                "last_name": last_name,
                "middle_initial": middle_initial,
                "worker_id": worker_id,
                "j_ra": j_ra,
                "classification": "Unknown",
                "st_hours": st["hours"],
                "ot_hours": ot["hours"],
                "dt_hours": dt["hours"],
                "total_hours": total_hours,
                "rate": st["rate"] or ot["rate"] or dt["rate"],
                "gross": gross_total,
                "deductions": deductions_total,
                "net": net_total,
            })

    return {
        "lines": parsed_rows,
        "totals": {"workers": len(parsed_rows)}
    }
