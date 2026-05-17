import os
import uuid

_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

DOC_DIRS: dict[str, str] = {
    "cpr":            os.path.join(_BASE, "documents", "cprs"),
    "fringe_plan":    os.path.join(_BASE, "documents", "fringe_plans"),
    "deduction_form": os.path.join(_BASE, "documents", "deduction_forms"),
    "apprentice_cert": os.path.join(_BASE, "documents", "apprentice_certs"),
    "wage_schedule":  os.path.join(_BASE, "data", "wage_schedules"),
}

VALID_DOC_TYPES = frozenset(DOC_DIRS)


def _ensure_dirs() -> None:
    for path in DOC_DIRS.values():
        os.makedirs(path, exist_ok=True)


def save_document(file_data: bytes, doc_type: str, original_filename: str) -> tuple[str, str]:
    """Save uploaded bytes to the appropriate directory. Returns (doc_id, file_path)."""
    if doc_type not in DOC_DIRS:
        raise ValueError(f"Unknown doc_type '{doc_type}'. Must be one of: {', '.join(DOC_DIRS)}")
    _ensure_dirs()
    doc_id = uuid.uuid4().hex[:12]
    ext = os.path.splitext(original_filename)[1].lower() or ".pdf"
    file_path = os.path.join(DOC_DIRS[doc_type], f"{doc_id}{ext}")
    with open(file_path, "wb") as fh:
        fh.write(file_data)
    return doc_id, file_path


def delete_document(file_path: str) -> None:
    if file_path and os.path.exists(file_path):
        os.remove(file_path)
