"""
Auto-discovery of supporting documents for WH-347 audit.

Resolves wage schedules, apprentice certs, and fringe plans from local
folder trees matching LCPtracker project structure:

  <docs_root>/documents/cprs/
  <docs_root>/documents/apprentice_certs/
  <docs_root>/documents/fringe_plans/
  <docs_root>/documents/deduction_forms/
  <docs_root>/data/wage_schedules/
"""

import os
import re


# ---------------------------------------------------------------------------
# Folder helpers
# ---------------------------------------------------------------------------

def _pdf_files(directory: str) -> list[str]:
    """Return all PDF file paths in directory (non-recursive)."""
    if not directory or not os.path.isdir(directory):
        return []
    return [
        os.path.join(directory, f)
        for f in sorted(os.listdir(directory))
        if f.lower().endswith(".pdf")
    ]


def _excel_files(directory: str) -> list[str]:
    if not directory or not os.path.isdir(directory):
        return []
    return [
        os.path.join(directory, f)
        for f in sorted(os.listdir(directory))
        if f.lower().endswith((".xlsx", ".xls"))
    ]


# ---------------------------------------------------------------------------
# Wage-schedule discovery
# ---------------------------------------------------------------------------

_WD_PATTERN = re.compile(
    r"([A-Z]{2}\d{4,}-?\d+)",   # e.g. WA20250002, FL2024-001
    re.IGNORECASE,
)


def find_wage_schedule(wage_det_number: str | None, schedules_dir: str) -> str | None:
    """
    Return path to the best-matching wage schedule Excel file.

    Strategy:
    1. If wage_det_number is known, scan filenames for that string (case-insensitive).
    2. Fall back to the single Excel file in the directory (if exactly one exists).
    3. Return None if nothing found.
    """
    candidates = _excel_files(schedules_dir)
    if not candidates:
        return None

    if wage_det_number:
        needle = wage_det_number.strip().lower()
        for path in candidates:
            if needle in os.path.basename(path).lower():
                return path

    # Fallback: use the only file
    if len(candidates) == 1:
        return candidates[0]

    return None


# ---------------------------------------------------------------------------
# Apprentice-cert discovery
# ---------------------------------------------------------------------------

def list_apprentice_certs(certs_dir: str) -> list[str]:
    """Return all apprentice cert PDFs in the directory."""
    return _pdf_files(certs_dir)


# ---------------------------------------------------------------------------
# Fringe-plan discovery
# ---------------------------------------------------------------------------

def list_fringe_plans(plans_dir: str) -> list[str]:
    """Return all fringe plan PDFs in the directory."""
    return _pdf_files(plans_dir)


# ---------------------------------------------------------------------------
# CPR discovery (batch mode)
# ---------------------------------------------------------------------------

def list_cprs(cprs_dir: str) -> list[str]:
    """Return all CPR PDFs in the directory, sorted by name."""
    return _pdf_files(cprs_dir)


# ---------------------------------------------------------------------------
# Main resolver
# ---------------------------------------------------------------------------

def resolve_docs(
    parsed_header: dict,
    docs_root: str | None = None,
    data_root: str | None = None,
) -> dict:
    """
    Auto-discover all supporting documents for a CPR audit.

    Parameters
    ----------
    parsed_header : dict
        The ``header`` sub-dict from ``extract_wh347_data()``.  Used to
        extract the wage determination number for schedule matching.
    docs_root : str or None
        Root directory that contains a ``documents/`` sub-tree.
        Defaults to ``wh347_auditor/`` inside the project package.
    data_root : str or None
        Root directory that contains a ``data/`` sub-tree.
        Defaults to same as docs_root.

    Returns
    -------
    dict with keys:
        wage_schedule   : str or None  — path to matched Excel file
        apprentice_certs: list[str]    — cert PDF paths
        fringe_plans    : list[str]    — fringe plan PDF paths
        deduction_forms : list[str]    — deduction form PDF paths
        wage_det_number : str or None  — number used for matching
    """
    _pkg = os.path.join(os.path.dirname(os.path.abspath(__file__)), "wh347_auditor")
    if docs_root is None:
        docs_root = _pkg
    if data_root is None:
        data_root = _pkg

    schedules_dir     = os.path.join(data_root,  "data",      "wage_schedules")
    certs_dir         = os.path.join(docs_root,  "documents", "apprentice_certs")
    plans_dir         = os.path.join(docs_root,  "documents", "fringe_plans")
    deductions_dir    = os.path.join(docs_root,  "documents", "deduction_forms")

    wage_det = (
        str(parsed_header.get("wage_determination_number", "") or "").strip() or None
    )

    wage_schedule = find_wage_schedule(wage_det, schedules_dir)

    return {
        "wage_schedule":    wage_schedule,
        "apprentice_certs": list_apprentice_certs(certs_dir),
        "fringe_plans":     list_fringe_plans(plans_dir),
        "deduction_forms":  _pdf_files(deductions_dir),
        "wage_det_number":  wage_det,
    }
