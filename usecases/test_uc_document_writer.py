"""UC-DOCUMENT-WRITER: the module stores a document and persists an extraction (Week 2, stage 2).

No model is involved. The extraction is a canned LabDocument, so this proves the write path on
its own: the document lands in the patient's Documents, the results land in the procedure
chain, and they read back as FHIR Observations and in Lab Overview. Everything the module
writes is marked machine-extracted and never clinician-reviewed.

Needs OE_DOCTOR_PASS (doctor1) and database access for the checks and the cleanup.

    $env:OPENEMR_BASE_URL="https://localhost:9300"; $env:OE_PASS="pass"; $env:OE_DOCTOR_PASS="<doctor1 pw>"
    .venv\\Scripts\\python -m pytest test_uc_document_writer.py
"""

import base64
import json

import pytest

import test_uc_copilot as uc
from conftest import BASE_URL, FHIR, db_query

API = f"{uc.MODULE}/api.php"
DEMOGRAPHICS = f"{BASE_URL}/interface/patient_file/summary/demographics.php"
LAB_OVERVIEW = f"{BASE_URL}/interface/patient_file/summary/labdata.php"

IN_PANEL = 3            # doctor1's (users.id 8)
OUT_OF_PANEL = 30       # doctor2's
DOCTOR1_ID = 8
POTASSIUM_LOINC = "2823-3"

# The smallest valid PDF: one blank page. Enough to be stored; extraction is not exercised here.
MINIMAL_PDF = (
    b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
    b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
    b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 200 200]>>endobj\n"
    b"xref\n0 4\n0000000000 65535 f \n0000000009 00000 n \n0000000052 00000 n \n0000000101 00000 n \n"
    b"trailer<</Size 4/Root 1 0 R>>\nstartxref\n160\n%%EOF\n"
)


def cite(doc_id, field, quote, page=1):
    return {"source_id": f"doc:{doc_id}", "page": page, "field": field, "quote": quote}


def supported(doc_id, value, field, quote=None, confidence=0.9):
    return {"value": value, "confidence": confidence, "citation": cite(doc_id, field, quote or value)}


ABSENT = {"value": None, "confidence": 0.0, "citation": None}


def lab_document(doc_id, ordering_provider=ABSENT):
    return {
        "doc_type": "lab_pdf", "source_id": f"doc:{doc_id}", "page_count": 1,
        "patient_ref": supported(doc_id, "Patient 3", "patient"),
        "report_date": supported(doc_id, "2026-09-18", "report_date"),
        "performing_lab": supported(doc_id, "Metro Clinical Labs", "performing_lab"),
        "ordering_provider": ordering_provider,
        "results": [
            {"test_name": supported(doc_id, "Potassium", "test_name"),
             "value": supported(doc_id, "5.4", "value", "Potassium 5.4 mmol/L H"),
             "unit": supported(doc_id, "mmol/L", "unit"),
             "reference_range": supported(doc_id, "3.5-5.0", "reference_range"),
             "collection_date": supported(doc_id, "2026-09-17", "collection_date"),
             "abnormal_flag": supported(doc_id, "H", "abnormal_flag")},
            {"test_name": supported(doc_id, "Sodium", "test_name"),
             "value": supported(doc_id, "140", "value", "Sodium 140 mmol/L"),
             "unit": supported(doc_id, "mmol/L", "unit"),
             "reference_range": supported(doc_id, "135-145", "reference_range"),
             "collection_date": supported(doc_id, "2026-09-17", "collection_date"),
             "abnormal_flag": ABSENT},
        ],
    }


def puuid_of(pid: int) -> str:
    rows = db_query(
        "SELECT LOWER(CONCAT_WS('-', SUBSTR(HEX(uuid),1,8), SUBSTR(HEX(uuid),9,4), SUBSTR(HEX(uuid),13,4), "
        f"SUBSTR(HEX(uuid),17,4), SUBSTR(HEX(uuid),21))) FROM patient_data WHERE pid = {pid}"
    )
    return rows[0][0]


def decoded_comment(row):
    return base64.b64decode(row).decode("utf-8", "replace")


@pytest.fixture(scope="module")
def doctor():
    if not uc.DOCTOR_PASS:
        pytest.skip("OE_DOCTOR_PASS not set")
    session = uc.ui_login("doctor1", uc.DOCTOR_PASS)
    session.get(f"{DEMOGRAPHICS}?set_pid={IN_PANEL}", timeout=120)   # active patient for Lab Overview
    return session


@pytest.fixture(scope="module")
def headers(doctor):
    return {"X-Copilot-Csrf": uc.csrf_from_page(doctor)}


@pytest.fixture(scope="module")
def created():
    """Ids created by this module, removed at the end so the demo database stays as it was."""
    ids = {"documents": [], "orders": []}
    yield ids
    for order_id in ids["orders"]:
        db_query(f"DELETE prs FROM procedure_result prs JOIN procedure_report pr ON pr.procedure_report_id = prs.procedure_report_id "
                 f"WHERE pr.procedure_order_id = {order_id}")
        db_query(f"DELETE FROM procedure_report WHERE procedure_order_id = {order_id}")
        db_query(f"DELETE FROM procedure_order_code WHERE procedure_order_id = {order_id}")
        db_query(f"DELETE FROM procedure_order WHERE procedure_order_id = {order_id}")
    for doc_id in ids["documents"]:
        db_query(f"DELETE FROM categories_to_documents WHERE document_id = {doc_id}")
        db_query(f"DELETE FROM documents WHERE id = {doc_id}")


def attach(doctor, headers, pid, name="metro-labs.pdf", doc_type="lab_pdf"):
    return doctor.post(f"{API}?action=attach&context=patient",
                       data={"pid": pid, "doc_type": doc_type, "extract": "0"},   # stage 2: store only, no model
                       files={"file": (name, MINIMAL_PDF, "application/pdf")},
                       headers=headers, timeout=60)


def persist(doctor, headers, pid, doc_id, extraction):
    return doctor.post(f"{API}?action=persist_extraction&context=patient",
                       json={"pid": pid, "doc_id": doc_id, "doc_type": "lab_pdf", "extraction": extraction},
                       headers=headers, timeout=60)


# --- the document lands in the patient's Documents ------------------------------

def test_attach_stores_the_document_under_lab_report(doctor, headers, created):
    resp = attach(doctor, headers, IN_PANEL)
    assert resp.status_code == 200, resp.text[:300]
    body = resp.json()
    doc_id = body["doc_id"]
    created["documents"].append(doc_id)
    assert body["doc_type"] == "lab_pdf" and body["processed"] is False and body["reason"] == "stored only"

    rows = db_query(f"SELECT d.foreign_id, d.mimetype, c.name FROM documents d "
                    f"JOIN categories_to_documents cd ON cd.document_id = d.id JOIN categories c ON c.id = cd.category_id WHERE d.id = {doc_id}")
    assert rows == [[str(IN_PANEL), "application/pdf", "Lab Report"]]


def test_attach_for_a_patient_outside_the_panel_is_refused(doctor, headers):
    resp = attach(doctor, headers, OUT_OF_PANEL)
    assert resp.status_code == 403 and resp.json()["state"] == "access_denied"
    assert db_query("SELECT COUNT(*) FROM documents WHERE foreign_id = 30 AND name LIKE 'metro-labs%'") == [["0"]]


# --- the extraction lands in the procedure chain, marked machine-extracted -------

def test_persist_writes_the_chain_and_reads_back_as_fhir_observation(doctor, headers, created, api):
    doc_id = attach(doctor, headers, IN_PANEL, name="metro-labs-2.pdf").json()["doc_id"]
    created["documents"].append(doc_id)

    resp = persist(doctor, headers, IN_PANEL, doc_id, lab_document(doc_id))
    assert resp.status_code == 200, resp.text[:400]
    body = resp.json()
    created["orders"].append(body["order_id"])
    assert len(body["source_ids"]) == 2 and all(s.startswith("lab:") for s in body["source_ids"])
    assert body["skipped"] == [] and body["attributed_to"] == "import"

    order = db_query(f"SELECT provider_id, patient_id, history_order, external_id, lab_id, order_status FROM procedure_order "
                     f"WHERE procedure_order_id = {body['order_id']}")[0]
    assert order[1] == str(IN_PANEL) and order[2] == "1" and order[3] == f"doc:{doc_id}" and order[5] == "completed"
    assert order[0] != "0" and order[0] != str(DOCTOR1_ID), "an unmatched ordering provider must be the import provider"
    assert db_query(f"SELECT username, authorized FROM users WHERE id = {order[0]}") == [["docimport", "0"]]

    report = db_query(f"SELECT report_status, review_status, source FROM procedure_report WHERE procedure_order_id = {body['order_id']}")[0]
    assert report == ["final", "received", str(DOCTOR1_ID)], "the lab finalised it; no clinician has reviewed it"

    results = db_query(f"SELECT result_code, result_text, result, units, `range`, abnormal, result_status, document_id, facility, comments "
                       f"FROM procedure_result WHERE document_id = {doc_id} ORDER BY result_text")
    assert [r[:8] for r in results] == [
        [POTASSIUM_LOINC, "Potassium", "5.4", "mmol/L", "3.5-5.0", "high", "preliminary", str(doc_id)],
        ["2951-2", "Sodium", "140", "mmol/L", "135-145", "", "preliminary", str(doc_id)],
    ]
    assert results[0][8] == "Metro Clinical Labs" and "machine-extracted" in results[0][9]

    # FHIR read-back: the same path ChartReader uses. Status carries the marker.
    bundle = api.get(f"{FHIR}/Observation", params={"patient": puuid_of(IN_PANEL), "code": POTASSIUM_LOINC}, timeout=60).json()
    observations = [e["resource"] for e in bundle.get("entry", []) if e["resource"]["resourceType"] == "Observation"]
    ours = [o for o in observations if str(o.get("valueQuantity", {}).get("value")) in ("5.4", "5.40")]
    assert ours, f"no potassium 5.4 Observation for patient {IN_PANEL}: {json.dumps(bundle)[:400]}"
    assert ours[0]["status"] == "preliminary"

    # Lab Overview offers one checkbox per result_code, so the LOINC mapping is what makes the
    # result selectable at all; selecting it renders the value.
    page = doctor.get(LAB_OVERVIEW, timeout=60).text
    assert f"value={POTASSIUM_LOINC}" in page, "the mapped LOINC is not offered in Lab Overview"
    listing = doctor.post(LAB_OVERVIEW, data={"mode": "list", "value_code[]": [POTASSIUM_LOINC]}, timeout=60).text
    assert "5.4" in listing and "No parameters selected" not in listing

    # The audit row names the document and counts; it never carries a value.
    comment = decoded_comment(db_query("SELECT comments FROM log WHERE event = 'copilot-extraction-persisted' ORDER BY id DESC LIMIT 1")[0][0])
    assert f"doc={doc_id}" in comment and "results=2" in comment and "5.4" not in comment


def test_persist_is_idempotent_per_document(doctor, headers, created):
    doc_id = attach(doctor, headers, IN_PANEL, name="metro-labs-3.pdf").json()["doc_id"]
    created["documents"].append(doc_id)
    first = persist(doctor, headers, IN_PANEL, doc_id, lab_document(doc_id)).json()
    created["orders"].append(first["order_id"])
    second = persist(doctor, headers, IN_PANEL, doc_id, lab_document(doc_id)).json()
    assert second["already_persisted"] is True and second["order_id"] == first["order_id"]
    assert db_query(f"SELECT COUNT(*) FROM procedure_result WHERE document_id = {doc_id}") == [["2"]]


def test_ordering_provider_is_the_hospitalist_only_on_an_exact_match(doctor, headers, created):
    doc_id = attach(doctor, headers, IN_PANEL, name="metro-labs-4.pdf").json()["doc_id"]
    created["documents"].append(doc_id)
    body = persist(doctor, headers, IN_PANEL, doc_id,
                   lab_document(doc_id, ordering_provider=supported(doc_id, "Dana Reyes", "ordering_provider"))).json()
    created["orders"].append(body["order_id"])
    assert body["attributed_to"] == "hospitalist"
    assert db_query(f"SELECT provider_id FROM procedure_order WHERE procedure_order_id = {body['order_id']}") == [[str(DOCTOR1_ID)]]

    doc_id = attach(doctor, headers, IN_PANEL, name="metro-labs-5.pdf").json()["doc_id"]
    created["documents"].append(doc_id)
    body = persist(doctor, headers, IN_PANEL, doc_id,
                   lab_document(doc_id, ordering_provider=supported(doc_id, "Dr D. Reyes", "ordering_provider"))).json()
    created["orders"].append(body["order_id"])
    assert body["attributed_to"] == "import", "a near-miss on the name must not attribute the order to the clinician"


def test_a_value_without_a_citation_is_never_persisted(doctor, headers, created):
    doc_id = attach(doctor, headers, IN_PANEL, name="metro-labs-6.pdf").json()["doc_id"]
    created["documents"].append(doc_id)
    doc = lab_document(doc_id)
    doc["results"][1]["value"] = {"value": "140", "confidence": 0.9, "citation": None}   # a guess
    body = persist(doctor, headers, IN_PANEL, doc_id, doc).json()
    created["orders"].append(body["order_id"])
    assert len(body["source_ids"]) == 1 and body["skipped"] == [{"index": 1, "reason": "value has no citation"}]
    assert db_query(f"SELECT result_text FROM procedure_result WHERE document_id = {doc_id}") == [["Potassium"]]


def test_persist_refuses_a_document_that_belongs_to_another_patient(doctor, headers, created):
    doc_id = attach(doctor, headers, IN_PANEL, name="metro-labs-7.pdf").json()["doc_id"]
    created["documents"].append(doc_id)
    # doctor1 may act for pid 3, but this document is then claimed for a different in-panel patient.
    resp = persist(doctor, headers, 4, doc_id, lab_document(doc_id))
    assert resp.status_code == 403 and resp.json()["state"] == "access_denied"
    assert db_query(f"SELECT COUNT(*) FROM procedure_result WHERE document_id = {doc_id}") == [["0"]]
