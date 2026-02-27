import pdfplumber
import os


def extract_wh347_data(pdf_path):
    """
    Table-based WH-347 parser.
    Reads structured table cells instead of raw text lines.
    Much more stable for digital PDFs.
    """

    if not os.path.exists(pdf_path):
        raise FileNotFoundError(pdf_path)

    parsed_rows = []

    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:

            # Extract tables directly
            tables = page.extract_tables()

            for table in tables:
                if not table:
                    continue

                for row in table:
                    if not row:
                        continue

                    # Remove empty cells
                    cleaned = [cell.strip() if cell else "" for cell in row]

                    # WH-347 rows typically start with worker number
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

                        st_hours = float(cleaned[7] or 0)
                        ot_hours = float(cleaned[8] or 0)
                        dt_hours = float(cleaned[9] or 0)
                        total_hours = float(cleaned[10] or 0)

                        rate = float(cleaned[11] or 0)
                        gross = float(cleaned[12] or 0)
                        deductions = float(cleaned[13] or 0)
                        net = float(cleaned[14] or 0)

                    except Exception:
                        # Skip malformed rows
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

    return {
        "lines": parsed_rows,
        "totals": {"workers": len(parsed_rows)}
    }
