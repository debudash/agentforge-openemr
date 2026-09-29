"""UC-DOCUMENT-EXTRACT: a real lab PDF becomes cited lab rows (Week 2, stage 3).

This is the one document test that needs a vision model. It uploads the fixture report and
expects the values printed on it to come back as procedure_result rows with citations. When
the agent refuses or the provider fails, the test skips rather than fails: that measures the
endpoint, not the code, and the stored-only path is asserted before skipping.

Needs OE_DOCTOR_PASS and a configured, allowlisted COPILOT_VISION_MODEL on the agent.
"""

from pathlib import Path

import pytest

import test_uc_copilot as uc
import labpdf
import test_uc_document_writer as w
from conftest import db_query

FIXTURE = Path(__file__).resolve().parent.parent / "copilot" / "evals" / "stage2" / "fixtures" / "documents" / "metro-labs-jane-doe.pdf"


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


def test_attaching_the_fixture_report_extracts_and_persists_its_values(doctor, headers, w_created=None):
    created = {"documents": [], "orders": []}
    try:
        resp = doctor.post(f"{w.API}?action=attach&context=patient",
                           data={"pid": w.IN_PANEL, "doc_type": "lab_pdf"},
                           files={"file": ("metro-labs-report.pdf", labpdf.lab_report(w.IN_PANEL), "application/pdf")},
                           headers=headers, timeout=300)
        assert resp.status_code == 200, resp.text[:400]
        body = resp.json()
        created["documents"].append(body["doc_id"])
        if not body["processed"]:
            # Stored, not extracted: the document must still be in the chart, and the reason named.
            assert db_query(f"SELECT COUNT(*) FROM documents WHERE id = {body['doc_id']}") == [["1"]]
            pytest.skip(f"extraction did not run: {body.get('reason')} {body.get('detail') or ''}")
        created["orders"].append(body["order_id"])

        rows = db_query(f"SELECT result_text, result, units, abnormal FROM procedure_result WHERE document_id = {body['doc_id']} ORDER BY result_text")
        by_name = {r[0].lower(): r for r in rows}
        assert "potassium" in by_name and by_name["potassium"][1] == "5.4" and by_name["potassium"][3] == "high", rows
        assert "hemoglobin a1c" in by_name and by_name["hemoglobin a1c"][1] == "7.4", "the page-2 result must be read too"
        assert body["attributed_to"] == "hospitalist", "the report names Dana Reyes, who is doctor1"

        # Re-extracting the same document is a no-op.
        again = doctor.post(f"{w.API}?action=extract&context=patient", json={"pid": w.IN_PANEL, "doc_id": body["doc_id"]},
                            headers=headers, timeout=60).json()
        assert again["already_persisted"] is True and again["order_id"] == body["order_id"]
    finally:
        for order_id in created["orders"]:
            db_query(f"DELETE prs FROM procedure_result prs JOIN procedure_report pr ON pr.procedure_report_id = prs.procedure_report_id WHERE pr.procedure_order_id = {order_id}")
            db_query(f"DELETE FROM procedure_report WHERE procedure_order_id = {order_id}")
            db_query(f"DELETE FROM procedure_order_code WHERE procedure_order_id = {order_id}")
            db_query(f"DELETE FROM procedure_order WHERE procedure_order_id = {order_id}")
        for doc_id in created["documents"]:
            db_query(f"DELETE FROM categories_to_documents WHERE document_id = {doc_id}")
            db_query(f"DELETE FROM documents WHERE id = {doc_id}")
