"""
Claude-powered metadata extraction for uploaded documents.

Each doc_type has a tailored prompt that asks Claude to pull the fields
auditors care about.  Claude returns a JSON object; we parse and store it.
Wage schedules (Excel) are handled without Claude via pandas.
"""

import base64
import json
import os

import anthropic

MODEL = "claude-sonnet-4-20250514"

_PROMPTS: dict[str, str] = {
    "cpr": """
You are reviewing a WH-347 certified payroll report (CPR) exported from LCPtracker.
Extract the following fields and return ONLY a valid JSON object — no markdown, no prose:

{
  "contractor_name": "Business name from the form header",
  "contractor_address": "Business address",
  "contract_number": "Federal contract or project number",
  "project_name": "Name of the construction project",
  "project_location": "Project site address",
  "payroll_number": "Sequential payroll number for this contractor",
  "week_ending": "Week ending date as MM/DD/YYYY",
  "wage_determination_number": "Davis-Bacon wage determination number",
  "employee_names": ["list", "of", "employee", "full", "names"],
  "employee_count": 0
}

Use null for any field you cannot find. employee_names should be every worker
listed in the payroll rows (last name, first name order is fine).
""",

    "fringe_plan": """
You are reviewing a fringe benefit plan document submitted by a Davis-Bacon contractor.
Extract these fields and return ONLY a valid JSON object:

{
  "plan_name": "Name of the plan or administrator",
  "plan_type": "health | pension | vacation | training | annuity | other",
  "benefit_amount_per_hour": 0.00,
  "benefit_amount_type": "per_hour | monthly | annual | other",
  "effective_date": "MM/DD/YYYY or null",
  "expiration_date": "MM/DD/YYYY or null",
  "covered_employee_types": "journeymen | apprentices | all | other",
  "administrator_name": "Insurance company or plan administrator",
  "plan_number": "Policy or plan ID number"
}

Use null for any field you cannot find.
""",

    "deduction_form": """
You are reviewing a wage deduction authorization form for a Davis-Bacon project.
Extract these fields and return ONLY a valid JSON object:

{
  "employee_name": "Full name of the employee",
  "employee_id": "Employee ID (or last 4 of SSN if shown, otherwise null)",
  "deduction_type": "union dues | tool rental | housing | savings | other — describe it",
  "deduction_amount": 0.00,
  "deduction_frequency": "weekly | biweekly | monthly | per_hour | other",
  "authorization_date": "Date signed MM/DD/YYYY",
  "employer_name": "Contractor/employer name",
  "is_voluntary": true
}

Use null for any field you cannot find. is_voluntary should be true unless the
form indicates a mandatory or court-ordered deduction.
""",

    "apprentice_cert": """
You are reviewing an apprentice registration certificate for a Davis-Bacon project.
Extract these fields and return ONLY a valid JSON object:

{
  "employee_name": "Full name of the apprentice",
  "apprentice_id": "Registration or certificate number",
  "program_name": "Name of the registered apprenticeship program",
  "trade_classification": "Trade (e.g. Carpenter, Electrician, Ironworker)",
  "apprentice_level": 1,
  "total_levels": 4,
  "percentage": 60,
  "registration_date": "MM/DD/YYYY",
  "expiration_date": "MM/DD/YYYY or null",
  "registering_agency": "Agency that registered the apprenticeship"
}

apprentice_level and total_levels are integers (period/step numbers).
percentage is the wage percentage for this period (e.g. 60 means 60% of journeyman rate).
Use null for any field you cannot find.
""",
}


def extract_metadata(file_path: str, doc_type: str) -> dict:
    """Extract metadata from a document using Claude. Raises on hard errors."""
    if doc_type == "wage_schedule":
        return _extract_wage_schedule(file_path)

    if doc_type not in _PROMPTS:
        raise ValueError(f"No extraction prompt for doc_type: {doc_type}")

    with open(file_path, "rb") as fh:
        pdf_b64 = base64.standard_b64encode(fh.read()).decode("utf-8")

    client = anthropic.Anthropic()
    response = client.messages.create(
        model=MODEL,
        max_tokens=1024,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "document",
                        "source": {
                            "type": "base64",
                            "media_type": "application/pdf",
                            "data": pdf_b64,
                        },
                    },
                    {
                        "type": "text",
                        "text": _PROMPTS[doc_type].strip(),
                    },
                ],
            }
        ],
    )

    raw = response.content[0].text.strip()

    # Strip markdown fences if Claude wraps the JSON
    if raw.startswith("```"):
        parts = raw.split("```")
        raw = parts[1]
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.strip()

    return json.loads(raw)


def _extract_wage_schedule(file_path: str) -> dict:
    """Summarise an Excel wage schedule without calling Claude."""
    try:
        import pandas as pd
        df = pd.read_excel(file_path)
        return {
            "type": "wage_schedule",
            "row_count": len(df),
            "columns": list(df.columns),
        }
    except Exception as exc:
        return {"type": "wage_schedule", "error": str(exc)}
