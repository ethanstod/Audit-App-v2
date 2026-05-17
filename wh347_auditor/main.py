"""
WH-347 Certified Payroll Auditor — FastAPI application.

Endpoints
---------
GET  /health                          Server health check
POST /upload                          Upload a document (PDF or Excel)
GET  /documents                       List all documents (filterable)
GET  /documents/{doc_id}              Retrieve a single document record
DELETE /documents/{doc_id}            Delete a document and its file
"""

import json
import os
from datetime import datetime
from typing import Optional

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import JSONResponse

from wh347_auditor.storage.database import get_db, init_db, get_document, list_documents
from wh347_auditor.storage.document_store import (
    VALID_DOC_TYPES,
    delete_document,
    save_document,
)
from wh347_auditor.storage.extractor import extract_metadata

app = FastAPI(
    title="WH-347 Certified Payroll Auditor",
    description="Davis-Bacon Act compliance auditing for WH-347 certified payroll forms.",
    version="2.0.0",
)

ALLOWED_EXTENSIONS = {".pdf", ".xlsx", ".xls"}


@app.on_event("startup")
async def startup():
    init_db()


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

@app.get("/health", tags=["system"])
def health():
    return {"status": "ok", "service": "WH-347 Auditor v2"}


# ---------------------------------------------------------------------------
# Upload
# ---------------------------------------------------------------------------

@app.post("/upload", tags=["documents"])
async def upload_document(
    file: UploadFile = File(..., description="PDF or Excel file to upload"),
    doc_type: str = Form(
        ...,
        description=(
            "Document type: cpr | fringe_plan | deduction_form | "
            "apprentice_cert | wage_schedule"
        ),
    ),
    contractor_name: Optional[str] = Form(None, description="Override contractor name"),
    employee_name: Optional[str] = Form(None, description="Employee name (per-employee docs)"),
):
    """
    Upload a single document. Claude immediately extracts metadata and stores
    it in the database alongside the file path.

    - **cpr** — WH-347 certified payroll report (PDF)
    - **fringe_plan** — Fringe benefit plan document (PDF)
    - **deduction_form** — Wage deduction authorization (PDF)
    - **apprentice_cert** — Apprentice registration certificate (PDF)
    - **wage_schedule** — Prevailing wage rate table (Excel)
    """
    if doc_type not in VALID_DOC_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"doc_type must be one of: {', '.join(sorted(VALID_DOC_TYPES))}",
        )

    fname = file.filename or "upload"
    ext = os.path.splitext(fname)[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"File type '{ext}' not accepted. Allowed: {', '.join(ALLOWED_EXTENSIONS)}",
        )

    file_data = await file.read()
    doc_id, file_path = save_document(file_data, doc_type, fname)
    uploaded_at = datetime.utcnow().isoformat()

    # Insert stub record so we have a doc_id even if extraction fails
    with get_db() as conn:
        conn.execute(
            """
            INSERT INTO documents
                (id, doc_type, original_filename, file_path, uploaded_at,
                 contractor_name, employee_name, extraction_status)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'pending')
            """,
            (doc_id, doc_type, fname, file_path, uploaded_at, contractor_name, employee_name),
        )

    # Extract metadata via Claude
    try:
        metadata = extract_metadata(file_path, doc_type)

        # Merge any auto-detected fields into DB
        auto_contractor = contractor_name or metadata.get("contractor_name")
        auto_employee   = employee_name or metadata.get("employee_name")

        with get_db() as conn:
            conn.execute(
                """
                UPDATE documents SET
                    extracted_metadata = ?,
                    extraction_status  = 'done',
                    contractor_name    = ?,
                    employee_name      = ?,
                    week_ending        = ?,
                    payroll_number     = ?,
                    contract_number    = ?,
                    project_name       = ?
                WHERE id = ?
                """,
                (
                    json.dumps(metadata),
                    auto_contractor,
                    auto_employee,
                    metadata.get("week_ending"),
                    metadata.get("payroll_number"),
                    metadata.get("contract_number"),
                    metadata.get("project_name"),
                    doc_id,
                ),
            )

        return {
            "doc_id":             doc_id,
            "doc_type":           doc_type,
            "original_filename":  fname,
            "file_path":          file_path,
            "uploaded_at":        uploaded_at,
            "extraction_status":  "done",
            "extracted_metadata": metadata,
        }

    except Exception as exc:
        with get_db() as conn:
            conn.execute(
                "UPDATE documents SET extraction_status = 'failed' WHERE id = ?",
                (doc_id,),
            )
        return JSONResponse(
            status_code=207,
            content={
                "doc_id":            doc_id,
                "doc_type":          doc_type,
                "original_filename": fname,
                "file_path":         file_path,
                "uploaded_at":       uploaded_at,
                "extraction_status": "failed",
                "extraction_error":  str(exc),
                "message":           "File saved successfully but metadata extraction failed.",
            },
        )


# ---------------------------------------------------------------------------
# List / retrieve
# ---------------------------------------------------------------------------

@app.get("/documents", tags=["documents"])
def list_docs(
    doc_type: Optional[str] = None,
    contractor_name: Optional[str] = None,
):
    """List uploaded documents, optionally filtered by doc_type or contractor_name."""
    return list_documents(doc_type=doc_type, contractor_name=contractor_name)


@app.get("/documents/{doc_id}", tags=["documents"])
def get_doc(doc_id: str):
    """Retrieve a single document record by its ID."""
    doc = get_document(doc_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    return doc


# ---------------------------------------------------------------------------
# Delete
# ---------------------------------------------------------------------------

@app.delete("/documents/{doc_id}", tags=["documents"])
def delete_doc(doc_id: str):
    """Delete a document record and remove its file from disk."""
    doc = get_document(doc_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    delete_document(doc["file_path"])

    with get_db() as conn:
        conn.execute("DELETE FROM documents WHERE id = ?", (doc_id,))

    return {"deleted": doc_id}
