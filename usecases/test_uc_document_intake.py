"""UC-DOCUMENT-INTAKE: an intake form is stored, its extraction kept beside it, and nothing
reaches the clinical lists (Week 2, stage 5).

Model-free: the extraction is canned. What this proves is the safety decision -- what a form
says a patient takes or reacts to is a report, so it becomes a sidecar document under Medical
Record and never an allergy or medication row that looks clinician-confirmed.

Needs OE_DOCTOR_PASS (doctor1) and database access.
"""

import json
from pathlib import Path

import pytest

import test_uc_copilot as uc
import test_uc_document_writer as w
from conftest import db_query

FIXTURE = Path(__file__).resolve().parent.parent / "copilot" / "evals" / "stage2" / "fixtures" / "documents" / "intake-jane-doe.pdf"
DOC_ID_PLACEHOLDER = 0


def intake_extraction(doc_id):
    def f(value, field, quote=None):
        return {"value": value, "confidence": 0.9, "citation": {"source_id": f"doc:{doc_id}", "page": 1, "field": field, "quote": quote or value}}
    return {
        "doc_type": "intake_form", "source_id": f"doc:{doc_id}", "page_count": 1,
        "form_date": f("2026-09-16", "form_date", "Form date: 2026-09-16"),
        "demographics": {"name": f("Jane Doe", "name", "Patient: Jane Doe"), "dob": f("1962-04-03", "dob", "DOB: 1962-04-03"), "sex": f("F", "sex", "Sex: F")},
        "chief_concern": f("Headaches for two weeks, worse in the morning", "chief_concern"),
        "current_medications": [f("lisinopril 10 mg daily", "medication"), f("metformin 500 mg twice daily", "medication"),
                                f("ibuprofen 400 mg as needed", "medication")],
        "allergies": [f("penicillin (rash)", "allergy")],
        "family_history": [f("father: hypertension", "family_history"), f("mother: type 2 diabetes", "family_history")],
    }


@pytest.fixture(scope="module")
def doctor():
    if not uc.DOCTOR_PASS:
        pytest.skip("OE_DOCTOR_PASS not set")
    session = uc.ui_login("doctor1", uc.DOCTOR_PASS)
    session.get(f"{w.DEMOGRAPHICS}?set_pid={w.IN_PANEL}", timeout=120)
    return session


@pytest.fixture(scope="module")
def headers(doctor):
    return {"X-Copilot-Csrf": uc.csrf_from_page(doctor)}


@pytest.fixture(scope="module")
def created():
    ids = []
    yield ids
    for doc_id in ids:
        db_query(f"DELETE FROM categories_to_documents WHERE document_id = {doc_id}")
        db_query(f"DELETE FROM documents WHERE id = {doc_id}")


def lists_count(pid):
    return db_query(f"SELECT COUNT(*) FROM lists WHERE pid = {pid}")[0][0]


def test_intake_form_is_stored_under_medical_record(doctor, headers, created):
    resp = doctor.post(f"{w.API}?action=attach&context=patient",
                       data={"pid": w.IN_PANEL, "doc_type": "intake_form", "extract": "0"},
                       files={"file": ("intake-jane-doe.pdf", FIXTURE.read_bytes(), "application/pdf")},
                       headers=headers, timeout=60)
    assert resp.status_code == 200, resp.text[:300]
    body = resp.json()
    created.append(body["doc_id"])
    assert body["doc_type"] == "intake_form" and body["processed"] is False
    rows = db_query(f"SELECT c.name FROM categories_to_documents cd JOIN categories c ON c.id = cd.category_id WHERE cd.document_id = {body['doc_id']}")
    assert rows == [["Medical Record"]]


def test_persisting_an_intake_extraction_writes_a_sidecar_and_no_clinical_rows(doctor, headers, created):
    doc_id = doctor.post(f"{w.API}?action=attach&context=patient",
                         data={"pid": w.IN_PANEL, "doc_type": "intake_form", "extract": "0"},
                         files={"file": ("intake-jane-doe-2.pdf", FIXTURE.read_bytes(), "application/pdf")},
                         headers=headers, timeout=60).json()["doc_id"]
    created.append(doc_id)
    before = lists_count(w.IN_PANEL)

    resp = doctor.post(f"{w.API}?action=persist_extraction&context=patient",
                       json={"pid": w.IN_PANEL, "doc_id": doc_id, "doc_type": "intake_form", "extraction": intake_extraction(doc_id), "model": "canned"},
                       headers=headers, timeout=60)
    assert resp.status_code == 200, resp.text[:300]
    body = resp.json()
    created.append(body["sidecar_doc_id"])
    assert body["already_persisted"] is False and body["source_ids"] == [f"doc:{doc_id}"]

    # The safety decision: nothing the form reports became an allergy or medication row.
    assert lists_count(w.IN_PANEL) == before
    assert db_query(f"SELECT COUNT(*) FROM lists WHERE pid = {w.IN_PANEL} AND title LIKE '%penicillin%' AND date >= CURDATE()") == [["0"]]

    row = db_query(f"SELECT d.name, d.mimetype, d.foreign_id, c.name FROM documents d JOIN categories_to_documents cd ON cd.document_id = d.id "
                   f"JOIN categories c ON c.id = cd.category_id WHERE d.id = {body['sidecar_doc_id']}")[0]
    assert row == [f"copilot-extraction-{doc_id}.json", "application/json", str(w.IN_PANEL), "Medical Record"]

    again = doctor.post(f"{w.API}?action=persist_extraction&context=patient",
                        json={"pid": w.IN_PANEL, "doc_id": doc_id, "doc_type": "intake_form", "extraction": intake_extraction(doc_id)},
                        headers=headers, timeout=60).json()
    assert again["already_persisted"] is True and again["sidecar_doc_id"] == body["sidecar_doc_id"]

    status = doctor.post(f"{w.API}?action=extract&context=patient", json={"pid": w.IN_PANEL, "doc_id": doc_id, "doc_type": "intake_form"},
                         headers=headers, timeout=60).json()
    assert status["processed"] is True and status["already_persisted"] is True

    comment = w.decoded_comment(db_query("SELECT comments FROM log WHERE event = 'copilot-extraction-persisted' ORDER BY id DESC LIMIT 1")[0][0])
    assert f"doc={doc_id}" in comment and "type=intake_form" in comment and "penicillin" not in comment


def test_intake_sidecar_for_another_patients_form_is_refused(doctor, headers, created):
    doc_id = doctor.post(f"{w.API}?action=attach&context=patient",
                         data={"pid": w.IN_PANEL, "doc_type": "intake_form", "extract": "0"},
                         files={"file": ("intake-jane-doe-3.pdf", FIXTURE.read_bytes(), "application/pdf")},
                         headers=headers, timeout=60).json()["doc_id"]
    created.append(doc_id)
    resp = doctor.post(f"{w.API}?action=persist_extraction&context=patient",
                       json={"pid": 4, "doc_id": doc_id, "doc_type": "intake_form", "extraction": intake_extraction(doc_id)},
                       headers=headers, timeout=60)
    assert resp.status_code == 403 and resp.json()["state"] == "access_denied"
    assert db_query(f"SELECT COUNT(*) FROM documents WHERE name = 'copilot-extraction-{doc_id}.json'") == [["0"]]
