"""
Apprentice certificate parser with JSON sidecar cache.

Calls Claude once per cert PDF, then caches the extracted data as a
.json file beside the PDF so subsequent audits never re-call the API.

Usage
-----
    from cert_loader import load_all_certs, match_certs_to_workers

    certs = load_all_certs(["/path/to/cert1.pdf", "/path/to/cert2.pdf"])
    match_certs_to_workers(workers, certs)
"""

import base64
import json
import os
import re

import anthropic

MODEL = "claude-opus-4-7"

_SYSTEM_PROMPT = """You extract structured data from apprentice registration certificates for Davis-Bacon Act compliance audits. Return ONLY a valid JSON object — no markdown, no prose."""

_EXTRACTION_PROMPT = """Extract these fields from the apprentice registration certificate and return ONLY a valid JSON object:

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
  "registering_agency": "Agency that registered the apprenticeship (e.g. WSDOT, JATC, state apprenticeship council)"
}

apprentice_level and total_levels are integers (period/step numbers).
percentage is the wage percentage for this period (e.g. 60 means 60% of journeyman rate).
Use null for any field you cannot find."""


def _sidecar_path(pdf_path: str) -> str:
    return os.path.splitext(pdf_path)[0] + ".cert.json"


def _load_cached(pdf_path: str) -> dict | None:
    sidecar = _sidecar_path(pdf_path)
    if not os.path.exists(sidecar):
        return None
    try:
        with open(sidecar, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (json.JSONDecodeError, OSError):
        return None


def _save_cache(pdf_path: str, data: dict) -> None:
    sidecar = _sidecar_path(pdf_path)
    with open(sidecar, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)


def _extract_cert(pdf_path: str) -> dict:
    """Call Claude to extract cert fields. Returns parsed dict."""
    with open(pdf_path, "rb") as fh:
        pdf_b64 = base64.standard_b64encode(fh.read()).decode("utf-8")

    client = anthropic.Anthropic()
    response = client.messages.create(
        model=MODEL,
        max_tokens=512,
        system=[
            {
                "type": "text",
                "text": _SYSTEM_PROMPT,
                "cache_control": {"type": "ephemeral"},
            }
        ],
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
                        "cache_control": {"type": "ephemeral"},
                    },
                    {
                        "type": "text",
                        "text": _EXTRACTION_PROMPT,
                    },
                ],
            }
        ],
    )

    raw = response.content[0].text.strip()
    if raw.startswith("```"):
        parts = raw.split("```")
        raw = parts[1]
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.strip()

    return json.loads(raw)


def load_cert(pdf_path: str, force_refresh: bool = False) -> dict:
    """
    Return extracted cert data for one PDF, using cache if available.

    The cache is stored as ``<cert_name>.cert.json`` beside the PDF.
    Pass ``force_refresh=True`` to re-call Claude even if cache exists.
    """
    if not force_refresh:
        cached = _load_cached(pdf_path)
        if cached is not None:
            return cached

    data = _extract_cert(pdf_path)
    data["_source_file"] = pdf_path
    _save_cache(pdf_path, data)
    return data


def load_all_certs(pdf_paths: list[str], force_refresh: bool = False) -> list[dict]:
    """
    Load (and cache) all cert PDFs. Skips files that fail to parse.

    Returns list of cert dicts, each with an added ``_source_file`` key.
    """
    results = []
    for path in pdf_paths:
        try:
            cert = load_cert(path, force_refresh=force_refresh)
            if "_source_file" not in cert:
                cert["_source_file"] = path
            results.append(cert)
        except Exception as exc:
            print(f"    [!] Could not parse cert {os.path.basename(path)}: {exc}")
    return results


# ---------------------------------------------------------------------------
# Worker matching
# ---------------------------------------------------------------------------

def _normalize_name(name: str) -> str:
    return re.sub(r"[^a-z]", "", name.lower())


def _name_match(cert_name: str | None, worker_first: str, worker_last: str) -> bool:
    if not cert_name:
        return False
    cn = _normalize_name(cert_name)
    fn = _normalize_name(worker_first or "")
    ln = _normalize_name(worker_last or "")
    return fn and ln and fn in cn and ln in cn


def match_certs_to_workers(workers: list[dict], certs: list[dict]) -> None:
    """
    Mutate each RA worker dict in-place, adding an ``apprentice_cert`` key
    if a matching cert is found.

    Matching is done by:
    1. worker_id == apprentice_id (exact, if both present)
    2. first + last name substring match against cert employee_name
    """
    ra_workers = [w for w in workers if str(w.get("worker_type", "")).upper() == "RA"]
    if not ra_workers or not certs:
        return

    for worker in ra_workers:
        wid = str(worker.get("worker_id", "")).strip()
        first = str(worker.get("first_name", "")).strip()
        last  = str(worker.get("last_name",  "")).strip()

        matched = None
        for cert in certs:
            cert_id = str(cert.get("apprentice_id", "")).strip()
            if wid and cert_id and wid == cert_id:
                matched = cert
                break
            if _name_match(cert.get("employee_name"), first, last):
                matched = cert
                break

        if matched:
            worker["apprentice_cert"] = matched
            if not worker.get("apprentice_period") and matched.get("apprentice_level"):
                worker["apprentice_period"] = matched["apprentice_level"]
            if not worker.get("apprentice_percentage") and matched.get("percentage"):
                worker["apprentice_percentage"] = matched["percentage"]
