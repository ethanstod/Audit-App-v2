import json
import os
import sqlite3
from contextlib import contextmanager

_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(_BASE, "data", "audit.db")


@contextmanager
def get_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    with get_db() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS documents (
                id                  TEXT PRIMARY KEY,
                doc_type            TEXT NOT NULL,
                original_filename   TEXT,
                file_path           TEXT,
                uploaded_at         TEXT,
                contractor_name     TEXT,
                contractor_id       TEXT,
                employee_name       TEXT,
                employee_id         TEXT,
                week_ending         TEXT,
                payroll_number      TEXT,
                contract_number     TEXT,
                project_name        TEXT,
                extracted_metadata  TEXT,
                extraction_status   TEXT DEFAULT 'pending'
            );

            CREATE TABLE IF NOT EXISTS audit_runs (
                id              TEXT PRIMARY KEY,
                contractor_id   TEXT,
                contract_number TEXT,
                week_ending     TEXT,
                run_at          TEXT,
                overall_status  TEXT,
                report_json     TEXT
            );
        """)


def get_document(doc_id: str) -> dict | None:
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM documents WHERE id = ?", (doc_id,)
        ).fetchone()
    if not row:
        return None
    doc = dict(row)
    if doc.get("extracted_metadata"):
        doc["extracted_metadata"] = json.loads(doc["extracted_metadata"])
    return doc


def list_documents(doc_type: str | None = None, contractor_name: str | None = None) -> list[dict]:
    with get_db() as conn:
        if doc_type:
            rows = conn.execute(
                "SELECT * FROM documents WHERE doc_type = ? ORDER BY uploaded_at DESC",
                (doc_type,),
            ).fetchall()
        elif contractor_name:
            rows = conn.execute(
                "SELECT * FROM documents WHERE contractor_name LIKE ? ORDER BY uploaded_at DESC",
                (f"%{contractor_name}%",),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM documents ORDER BY uploaded_at DESC"
            ).fetchall()

    result = []
    for row in rows:
        doc = dict(row)
        if doc.get("extracted_metadata"):
            doc["extracted_metadata"] = json.loads(doc["extracted_metadata"])
        result.append(doc)
    return result
