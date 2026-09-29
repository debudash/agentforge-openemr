"""UC-DOCUMENT-PAGE: click-to-source (Week 2, stage 9).

A citation into a stored document opens the page it points at, with the quoted text boxed where
the PDF's own text layer places it. No model: a box is either where the text is, or absent.
Viewing a page is an audited read of the patient's document.
"""

import pytest

import test_uc_copilot as uc
import test_uc_document_extract as x
import test_uc_document_writer as w
from conftest import db_query


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
def stored(doctor, headers):
    body = doctor.post(f"{w.API}?action=attach&context=patient", data={"pid": w.IN_PANEL, "doc_type": "lab_pdf", "extract": "0"},
                       files={"file": ("metro-labs-page.pdf", x.FIXTURE.read_bytes(), "application/pdf")}, headers=headers, timeout=60).json()
    yield body["doc_id"]
    db_query(f"DELETE FROM categories_to_documents WHERE document_id = {body['doc_id']}")
    db_query(f"DELETE FROM documents WHERE id = {body['doc_id']}")


def page(doctor, headers, pid, doc_id, number, quotes):
    return doctor.post(f"{w.API}?action=page&context=patient", json={"pid": pid, "doc_id": doc_id, "page": number, "quotes": quotes},
                       headers=headers, timeout=120)


def test_a_cited_quote_is_boxed_on_its_page(doctor, headers, stored):
    resp = page(doctor, headers, w.IN_PANEL, stored, 1, ["Potassium", "Sodium                  140         mmol/L"])
    assert resp.status_code == 200, resp.text[:300]
    body = resp.json()
    assert body["pages"] == 2 and body["page"] == 1 and body["image_base64"].startswith("iVBORw0KGgo")
    assert [b["found"] for b in body["boxes"]] == [True, True]
    x0, y0, x1, y1 = body["boxes"][0]["bbox"]
    assert 0 <= x0 < x1 <= 1 and 0 <= y0 < y1 <= 1
    assert body["original_url"].endswith(f"document_id={stored}&as_file=false")
    comment = w.decoded_comment(db_query("SELECT comments FROM log WHERE event = 'copilot-document-viewed' ORDER BY id DESC LIMIT 1")[0][0])
    assert f"doc={stored}" in comment and "page=1" in comment and "Potassium" not in comment


def test_a_quote_not_on_the_page_is_reported_not_drawn(doctor, headers, stored):
    body = page(doctor, headers, w.IN_PANEL, stored, 1, ["Hemoglobin A1c"]).json()
    assert body["boxes"] == [{"quote": "Hemoglobin A1c", "found": False, "bbox": None}]
    assert page(doctor, headers, w.IN_PANEL, stored, 2, ["Hemoglobin A1c"]).json()["boxes"][0]["found"] is True


def test_a_page_the_document_lacks_is_refused(doctor, headers, stored):
    assert page(doctor, headers, w.IN_PANEL, stored, 3, ["x"]).status_code == 400


def test_another_patients_document_cannot_be_viewed(doctor, headers, stored):
    resp = page(doctor, headers, 4, stored, 1, ["Potassium"])
    assert resp.status_code == 403 and resp.json()["state"] == "access_denied"
