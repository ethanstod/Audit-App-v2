import pdfplumber
import re
import os


def extract_wh347_data(pdf_path):
    """
    Extracts worker data from a DIGITAL WH-347 PDF.

    Returns:
    {
        "lines": [
            {
                "row_number": int,
                "first_name": str,
                "last_name": str,
                "middle_initial": str,
                "worker_id": str,
                "j_ra": str,
                "classification": str,
                "st_hours": float,
                "ot_hours": float,
                "dt_hours": float,
                "total_hours": float,
                "rate": float,
                "gross": float,
                "deductions": float,
                "net": float
            }
        ],
        "totals": {"workers": int}
    }
    """

    if not os.path.exists(pdf_path):
        raise FileNotFoundError(f"File not found: {pdf_path}")

    def clean_line(text):
        return re.sub(r"\s+", " ", text.strip())

    def safe_float(value):
        try:
            value = re.sub(r"[^\d\.]", "", str(value))
            return float(value or 0)
        except:
            return 0.0

    # ---------------------------------------------------------
    # Extract all text lines
    # ---------------------------------------------------------
    lines = []

    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ""
            for raw in text.splitlines():
                cleaned = clean_line(raw)
                if cleaned:
                    lines.append(cleaned)

    # ---------------------------------------------------------
    # Split into worker blocks
    # ---------------------------------------------------------
    worker_blocks = []
    current_block = []

    for line in lines:
        # Worker rows start with row number + capital letter
        if re.match(r"^\d+\s+[A-Z]", line):
            if current_block:
                worker_blocks.append(current_block)
            current_block = [line]
        else:
            if current_block:
                current_block.append(line)

    if current_block:
        worker_blocks.append(current_block)

    parsed_rows = []

    name_pattern = re.compile(
        r"^(\d+)\s+([A-Z\-']+)\s+([A-Z\-']+)\s*([A-Z]?)\s+([A-Z0-9]{3,})\s+(J|RA)"
    )

    # ---------------------------------------------------------
    # Parse each worker block
    # ---------------------------------------------------------
    for block in worker_blocks:
        first_line = block[0]
        match = name_pattern.match(first_line)

        if not match:
            continue

        row_number = int(match.group(1))
        last_name = match.group(2).title()
        first_name = match.group(3).title()
        middle_initial = match.group(4).title() if match.group(4) else ""
        worker_id = match.group(5)
        j_ra = match.group(6)

        # Default pay structures
        st = {"hours": 0, "rate": 0, "gross": 0, "deductions": 0, "net": 0}
        ot = {"hours": 0, "rate": 0, "gross": 0, "deductions": 0, "net": 0}
        dt = {"hours": 0, "rate": 0, "gross": 0, "deductions": 0, "net": 0}

        for line in block:
            type_match = re.search(r"\b(ST|OT|DT)\b", line)
            if not type_match:
                continue

            nums = re.findall(r"\d+\.\d+", line)

            # We expect at least: hours | rate | gross | deductions | net
            if len(nums) < 5:
                continue

            nums = [safe_float(n) for n in nums]

            # Anchor from RIGHT side of row
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

        parsed_rows.append(
            {
                "row_number": row_number,
                "first_name": first_name,
                "last_name": last_name,
                "middle_initial": middle_initial,
                "worker_id": worker_id,
                "j_ra": j_ra,
                "classification": "Unknown",  # We enhance later
                "st_hours": round(st["hours"], 2),
                "ot_hours": round(ot["hours"], 2),
                "dt_hours": round(dt["hours"], 2),
                "total_hours": round(total_hours, 2),
                "rate": round(st["rate"] or ot["rate"] or dt["rate"], 2),
                "gross": round(gross_total, 2),
                "deductions": round(deductions_total, 2),
                "net": round(net_total, 2),
            }
        )

    return {
        "lines": parsed_rows,
        "totals": {"workers": len(parsed_rows)}
    }
