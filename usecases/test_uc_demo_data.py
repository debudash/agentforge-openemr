"""UC-DEMO-DATA: the Demo Data tab (validation tooling, Week 2).

It writes synthetic documents and files them in the chart unread, through the same storeDocument
an upload goes through, so the co-pilot finds them on its next run. The files stay in the folder
too, so the by-hand upload path can still be shown. Purge removes all of it: the files, the
documents, and the lab rows those documents produced, so a citation never outlives its page.

Needs OE_DOCTOR_PASS. The flag must be on for this instance (COPILOT_DEMO_TOOLS), or the actions
refuse and these cases skip.
"""

import re

import pytest

import test_uc_copilot as uc
import test_uc_document_writer as w
from conftest import db_query

VARIANTS = ["abnormal", "normal", "unreadable", "wrong_patient"]


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


def call(doctor, headers, action, body):
    return doctor.post(f"{w.API}?action={action}&context=patient", json=body, headers=headers, timeout=120)


@pytest.fixture(scope="module", autouse=True)
def enabled(doctor, headers):
    resp = call(doctor, headers, "demo_files", {"pid": w.IN_PANEL})
    if resp.status_code == 403:
        pytest.skip("COPILOT_DEMO_TOOLS is not enabled on this instance")
    yield
    call(doctor, headers, "demo_purge", {"pid": w.IN_PANEL})


def test_generate_writes_a_lab_report_and_an_intake_form_for_this_patient(doctor, headers):
    body = call(doctor, headers, "demo_generate", {"pid": w.IN_PANEL, "variant": "abnormal"}).json()
    assert [g["doc_type"] for g in body["generated"]] == ["lab_pdf", "intake_form"]
    assert all(g["name"].startswith("copilot-demo-") and g["bytes"] > 400 for g in body["generated"])
    assert body["directory"].endswith("demo/generated")


def test_generated_documents_are_filed_in_the_chart_unread(doctor, headers):
    """The point of the change: a generated document is in the chart, so the co-pilot finds it on
    its next run. A file the clinician still has to upload by hand is a step that exists only for
    the demo."""
    body = call(doctor, headers, "demo_generate", {"pid": w.IN_PANEL, "variant": "abnormal"}).json()
    doc_ids = [g["doc_id"] for g in body["generated"]]
    assert all(isinstance(d, int) and d > 0 for d in doc_ids), body

    listed = call(doctor, headers, "documents", {"pid": w.IN_PANEL}).json()
    by_id = {d["doc_id"]: d for d in listed["documents"]}
    for generated in body["generated"]:
        entry = by_id.get(generated["doc_id"])
        assert entry is not None, f"{generated['name']} is not in the chart"
        assert entry["doc_type"] == generated["doc_type"]
        assert entry["processed"] is False, "a generated document must arrive unread"
    assert listed["unprocessed"] >= 2


def test_the_generated_report_names_the_patient_it_was_generated_for(doctor, headers):
    name = call(doctor, headers, "demo_generate", {"pid": w.IN_PANEL, "variant": "abnormal"}).json()["generated"][0]["name"]
    pdf = doctor.get(f"{w.API}?action=demo_file&context=patient&pid={w.IN_PANEL}&name={name}", timeout=60)
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")
    expected = db_query(f"SELECT CONCAT(fname,' ',lname) FROM patient_data WHERE pid = {w.IN_PANEL}")[0][0]
    # The name is what makes a document's own patient reference agree with the chart it is filed in.
    assert expected.encode() in pdf.content


def test_each_generation_is_a_new_document_not_a_repeat(doctor, headers):
    first = call(doctor, headers, "demo_generate", {"pid": w.IN_PANEL, "variant": "abnormal"}).json()["generated"][0]["name"]
    second = call(doctor, headers, "demo_generate", {"pid": w.IN_PANEL, "variant": "abnormal"}).json()["generated"][0]["name"]
    listed = [f["name"] for f in call(doctor, headers, "demo_files", {"pid": w.IN_PANEL}).json()["files"]]
    assert first in listed and second in listed


@pytest.mark.parametrize("variant", VARIANTS)
def test_every_variant_generates(doctor, headers, variant):
    body = call(doctor, headers, "demo_generate", {"pid": w.IN_PANEL, "variant": variant}).json()
    assert len(body["generated"]) == 2


def test_an_unknown_variant_is_refused(doctor, headers):
    """Refused as a bad request, not as a server error: the variant is caller input."""
    assert call(doctor, headers, "demo_generate", {"pid": w.IN_PANEL, "variant": "../etc"}).status_code == 400


def test_a_file_outside_the_generated_set_cannot_be_downloaded(doctor, headers):
    for name in ["../../sites/default/sqlconf.php", "copilot-demo-nope.pdf"]:
        resp = doctor.get(f"{w.API}?action=demo_file&context=patient&pid={w.IN_PANEL}&name={name}", timeout=60)
        assert resp.status_code != 200 or not resp.content.startswith(b"%PDF"), name


def test_generating_for_a_patient_outside_the_panel_is_refused(doctor, headers):
    resp = call(doctor, headers, "demo_generate", {"pid": w.OUT_OF_PANEL, "variant": "abnormal"})
    assert resp.status_code == 403 and resp.json()["state"] == "access_denied"


def test_purge_clears_the_folder_and_leaves_nothing_it_did_not_generate(doctor, headers):
    call(doctor, headers, "demo_generate", {"pid": w.IN_PANEL, "variant": "abnormal"})
    before = db_query(f"SELECT COUNT(*) FROM documents WHERE foreign_id = {w.IN_PANEL} AND deleted = 0")[0][0]
    body = call(doctor, headers, "demo_purge", {"pid": w.IN_PANEL}).json()
    assert body["files"] >= 2 and body["files_remaining"] == []
    # Its own documents go; anything else in the chart stays exactly as it was.
    after = db_query(f"SELECT COUNT(*) FROM documents WHERE foreign_id = {w.IN_PANEL} AND deleted = 0")[0][0]
    assert int(after) == int(before) - body["documents"]
    assert db_query(f"SELECT COUNT(*) FROM documents WHERE foreign_id = {w.IN_PANEL} "
                    f"AND deleted = 0 AND name LIKE 'copilot-demo-%'") == [["0"]]


def test_a_report_naming_another_patient_is_read_but_never_filed(doctor, headers):
    """The cross-check the whole feature turns on: a document is filed under a patient by whoever
    uploaded it, and people misfile things. The name printed on the report is the document's own
    claim about whose results these are, and a mismatch is refused rather than reconciled."""
    gen = call(doctor, headers, "demo_generate", {"pid": w.IN_PANEL, "variant": "wrong_patient"}).json()
    name = gen["generated"][0]["name"]
    doc_id = gen["generated"][0]["doc_id"]
    pdf = doctor.get(f"{w.API}?action=demo_file&context=patient&pid={w.IN_PANEL}&name={name}", timeout=60).content
    assert b"Marlow Ashcombe" in pdf

    body = call(doctor, headers, "extract", {"pid": w.IN_PANEL, "doc_id": doc_id, "doc_type": "lab_pdf"}).json()
    try:
        if body.get("reason", "").startswith("extraction failed"):
            pytest.skip(f"the vision model was unavailable: {body['reason']}")
        assert body["processed"] is False, body
        assert body.get("patient_ref_mismatch") is True and "different patient" in body["reason"]
        # Stored for a human to look at, but nothing it says reached the chart.
        assert db_query(f"SELECT COUNT(*) FROM procedure_result WHERE document_id = {doc_id}") == [["0"]]
        assert db_query(f"SELECT COUNT(*) FROM documents WHERE id = {doc_id} AND deleted = 0") == [["1"]]
    finally:
        call(doctor, headers, "demo_purge", {"pid": w.IN_PANEL})


def test_a_report_naming_this_patient_is_filed(doctor, headers):
    """The same path with the matching name, so the refusal above is the cross-check working and
    not merely extraction failing."""
    gen = call(doctor, headers, "demo_generate", {"pid": w.IN_PANEL, "variant": "abnormal"}).json()
    doc_id = gen["generated"][0]["doc_id"]
    body = call(doctor, headers, "extract", {"pid": w.IN_PANEL, "doc_id": doc_id, "doc_type": "lab_pdf"}).json()
    try:
        if body.get("reason", "").startswith("extraction failed"):
            pytest.skip(f"the vision model was unavailable: {body['reason']}")
        assert body["processed"] is True and body.get("patient_ref_mismatch") is None
        assert len(body["source_ids"]) >= 3
    finally:
        call(doctor, headers, "demo_purge", {"pid": w.IN_PANEL})


def test_the_what_changed_citation_opens_a_page_with_the_quote_boxed(doctor, headers):
    """The requirement's end state: a clinical claim carries citation metadata a program can act
    on, and acting on it draws a box on the page. This is the claim a clinician clicks first, and
    it used to open page 1 with nothing highlighted because the citation carried no quote."""
    call(doctor, headers, "demo_generate", {"pid": w.IN_PANEL, "variant": "abnormal"})
    doctor.post(f"{w.API}?action=open_patient&context=patient", json={"pid": w.IN_PANEL}, headers=headers, timeout=300)
    body = doctor.post(f"{w.API}?action=supervise&context=patient", json={"pid": w.IN_PANEL},
                       headers=headers, timeout=600).json()
    try:
        documents = [c for c in body.get("citations") or [] if c["source_type"] == "document"]
        assert documents, "the supervisor reported no document citations"
        # Every document citation identifies itself; the ones that point into a page carry "p<n>"
        # and must resolve to a box. A document cited as a whole names the chart section instead,
        # which is honest -- there is no single page such a claim is about.
        for citation in documents:
            assert citation["page_or_section"] and citation["quote_or_value"], citation
        anchored = [c for c in documents if re.fullmatch(r"p\d+", str(c["page_or_section"]))]
        assert anchored, f"no document citation pointed into a page: {[c['page_or_section'] for c in documents]}"
        for citation in anchored:
            page = int(str(citation["page_or_section"]).lstrip("p"))
            rendered = doctor.post(f"{w.API}?action=page&context=patient",
                                   json={"pid": w.IN_PANEL, "doc_id": int(citation["source_id"].split(":")[1]),
                                         "page": page, "quotes": [citation["quote_or_value"]]},
                                   headers=headers, timeout=300).json()
            assert rendered["boxes"][0]["found"] is True, f"{citation['quote_or_value']!r} not located"
            x0, y0, x1, y1 = rendered["boxes"][0]["bbox"]
            assert 0 <= x0 < x1 <= 1 and 0 <= y0 < y1 <= 1
    finally:
        call(doctor, headers, "demo_purge", {"pid": w.IN_PANEL})
