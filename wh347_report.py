from datetime import datetime
import os


def generate_wh347_html_report(report_data):
    """
    Generates an HTML report summarizing audit results.
    """

    parsed_data = report_data.get("parsed_data", {})
    workers = parsed_data.get("lines", [])

    math_results = report_data.get("math", {})
    pay_results = report_data.get("pay", {})

    math_by_row = math_results.get("by_row", {})
    pay_by_row = pay_results.get("by_row", {})

    overall_pass = report_data.get("passed", False)

    output_path = os.path.join(os.getcwd(), "report_wh347.html")
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def combine_status(row_number):
        statuses = []
        reasons = []

        if row_number in math_by_row:
            statuses.append(math_by_row[row_number]["result"])
            if math_by_row[row_number]["reason"]:
                reasons.append("Math: " + math_by_row[row_number]["reason"])

        if row_number in pay_by_row:
            statuses.append(pay_by_row[row_number]["result"])
            if pay_by_row[row_number]["reason"]:
                reasons.append("Pay: " + pay_by_row[row_number]["reason"])

        if "FAIL" in statuses:
            return "FAIL", " | ".join(reasons)
        if "WARN" in statuses:
            return "WARN", " | ".join(reasons)
        return "PASS", ""

    rows_html = ""

    for worker in workers:
        row_no = worker.get("row_number")

        result, reason = combine_status(row_no)

        badge_color = {
            "PASS": "#28a745",
            "FAIL": "#dc3545",
            "WARN": "#ffc107"
        }.get(result, "#999")

        rows_html += f"""
        <tr>
            <td>{row_no}</td>
            <td>{worker.get('last_name')} {worker.get('first_name')}</td>
            <td>{worker.get('classification')}</td>
            <td>{worker.get('st_hours')}</td>
            <td>{worker.get('ot_hours')}</td>
            <td>{worker.get('dt_hours')}</td>
            <td>{worker.get('total_hours')}</td>
            <td>{worker.get('rate')}</td>
            <td>{worker.get('gross')}</td>
            <td>{worker.get('deductions')}</td>
            <td>{worker.get('net')}</td>
            <td style="color:{badge_color}; font-weight:bold;">
                {result}
                <div style="font-size:12px; color:#ccc;">{reason}</div>
            </td>
        </tr>
        """

    html = f"""
    <html>
    <head>
        <title>WH-347 Audit Report</title>
        <style>
            body {{
                background:#1e1e1e;
                color:white;
                font-family:Arial;
                padding:20px;
            }}
            table {{
                width:100%;
                border-collapse:collapse;
                margin-top:20px;
            }}
            th, td {{
                border:1px solid #444;
                padding:8px;
                text-align:center;
            }}
            th {{
                background:#333;
            }}
        </style>
    </head>
    <body>
        <h1>WH-347 Audit Report</h1>
        <p>Date: {timestamp}</p>
        <h2>Status: {"PASS" if overall_pass else "FAIL"}</h2>

        <table>
            <tr>
                <th>#</th>
                <th>Worker</th>
                <th>Classification</th>
                <th>ST</th>
                <th>OT</th>
                <th>DT</th>
                <th>Total</th>
                <th>Rate</th>
                <th>Gross</th>
                <th>Deductions</th>
                <th>Net</th>
                <th>Status</th>
            </tr>
            {rows_html}
        </table>
    </body>
    </html>
    """

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)

    return output_path
