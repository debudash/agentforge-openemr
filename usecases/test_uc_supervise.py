"""UC-SUPERVISE: the supervisor graph through the module (Week 2, stage 7).

Two paths. With no unread documents the graph goes straight to the brief. With an unread lab
report it reads the document, hands back to the module to persist, and resumes with the re-read
chart. On the free tier the read may be rate-limited; then the graph still finishes, the brief
still comes, and "what changed" says the document could not be read. Both outcomes are asserted
rather than skipped, because both are correct behaviour.

Needs OE_DOCTOR_PASS and the agent with a model for the brief (skips if the agent refuses the session).
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


@pytest.fixture(scope="module", autouse=True)
def no_fixture_orphans():
    """Earlier test runs can leave fixture-named documents behind (a killed run, a crashed cleanup).
    They would make "nothing unread" false, so remove them first. Only fixture names are touched."""
    ids = [r[0] for r in db_query(f"SELECT id FROM documents WHERE foreign_id = {w.IN_PANEL} AND "
                                  "(name LIKE 'metro-labs%' OR name LIKE 'intake-jane-doe%' OR name LIKE 'copilot-extraction-%')")]
    for doc_id in ids:
        order = db_query(f"SELECT DISTINCT pr.procedure_order_id FROM procedure_result prs JOIN procedure_report pr "
                         f"ON pr.procedure_report_id = prs.procedure_report_id WHERE prs.document_id = {doc_id}")
        for (order_id,) in order:
            db_query(f"DELETE prs FROM procedure_result prs JOIN procedure_report pr ON pr.procedure_report_id = prs.procedure_report_id WHERE pr.procedure_order_id = {order_id}")
            db_query(f"DELETE FROM procedure_report WHERE procedure_order_id = {order_id}")
            db_query(f"DELETE FROM procedure_order_code WHERE procedure_order_id = {order_id}")
            db_query(f"DELETE FROM procedure_order WHERE procedure_order_id = {order_id}")
        db_query(f"DELETE FROM categories_to_documents WHERE document_id = {doc_id}")
        db_query(f"DELETE FROM documents WHERE id = {doc_id}")
    yield


def open_patient(doctor, headers):
    resp = doctor.post(f"{w.API}?action=open_patient&context=patient", json={"pid": w.IN_PANEL}, headers=headers, timeout=120)
    if resp.status_code == 503:
        pytest.skip(f"agent refused the session: {resp.json().get('reason')}")
    assert resp.status_code == 200, resp.text[:300]


def supervise(doctor, headers):
    return doctor.post(f"{w.API}?action=supervise&context=patient", json={"pid": w.IN_PANEL}, headers=headers, timeout=600)


def edges(summary):
    return [(h["from"], h["to"]) for h in summary.get("handoffs", [])]


def test_with_nothing_unread_the_supervisor_briefs_straight_away(doctor, headers):
    open_patient(doctor, headers)
    resp = supervise(doctor, headers)
    assert resp.status_code == 200, resp.text[:400]
    body = resp.json()
    assert body["phase"] == "done" and body["brief"]["pid"] == w.IN_PANEL
    assert ("supervisor", "intake_extractor") not in edges(body)
    assert edges(body)[0] == ("supervisor", "evidence_retriever") and edges(body)[-1] == ("supervisor", "clinician")
    assert all(h["reason"] for h in body["handoffs"]), "every handoff names its reason"


def test_an_unread_lab_report_is_read_persisted_and_reported_or_honestly_not(doctor, headers):
    created = {"documents": [], "orders": []}
    try:
        stored = doctor.post(f"{w.API}?action=attach&context=patient",
                             data={"pid": w.IN_PANEL, "doc_type": "lab_pdf", "extract": "0"},
                             files={"file": ("metro-labs-supervise.pdf", x.FIXTURE.read_bytes(), "application/pdf")},
                             headers=headers, timeout=60).json()
        created["documents"].append(stored["doc_id"])
        open_patient(doctor, headers)
        resp = supervise(doctor, headers)
        assert resp.status_code == 200, resp.text[:400]
        body = resp.json()
        assert body["phase"] == "done" and body["brief"], "the graph must finish with a brief either way"
        assert ("supervisor", "intake_extractor") in edges(body) and ("intake_extractor", "supervisor") in edges(body)
        change = [c for c in body["changes"] if f"doc:{stored['doc_id']}" in c["source_ids"]]
        assert change, f"no what-changed entry for the document: {body['changes']}"

        if body.get("extractions"):
            # Read and persisted: the module handed control back and the graph resumed.
            assert ("supervisor", "module") in edges(body) and ("module", "supervisor") in edges(body)
            persisted = [p for p in body["persisted"] if p["doc_id"] == stored["doc_id"]][0]
            created["orders"].append(persisted["order_id"])
            assert persisted["source_ids"] and "added to the chart" in change[0]["text"]
            rows = db_query(f"SELECT COUNT(*) FROM procedure_result WHERE document_id = {stored['doc_id']}")
            assert rows == [[str(len(persisted["source_ids"]))]]
        else:
            # Could not be read (free-tier quota is the usual reason): said plainly, nothing invented.
            assert body["failed"] and "could not be read" in change[0]["text"]
            assert ("supervisor", "module") not in edges(body)
            assert db_query(f"SELECT COUNT(*) FROM procedure_result WHERE document_id = {stored['doc_id']}") == [["0"]]

        comment = w.decoded_comment(db_query("SELECT comments FROM log WHERE event = 'copilot-supervise' ORDER BY id DESC LIMIT 1")[0][0])
        assert "handoffs=" in comment and "5.4" not in comment and "Jane" not in comment
    finally:
        for order_id in created["orders"]:
            db_query(f"DELETE prs FROM procedure_result prs JOIN procedure_report pr ON pr.procedure_report_id = prs.procedure_report_id WHERE pr.procedure_order_id = {order_id}")
            db_query(f"DELETE FROM procedure_report WHERE procedure_order_id = {order_id}")
            db_query(f"DELETE FROM procedure_order_code WHERE procedure_order_id = {order_id}")
            db_query(f"DELETE FROM procedure_order WHERE procedure_order_id = {order_id}")
        for doc_id in created["documents"]:
            db_query(f"DELETE FROM categories_to_documents WHERE document_id = {doc_id}")
            db_query(f"DELETE FROM documents WHERE id = {doc_id}")
