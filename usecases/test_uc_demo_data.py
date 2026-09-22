"""UC-DEMO-DATA: the Demo Data tab (validation tooling, Week 2).

It writes synthetic documents to a folder so the ingestion flow can be exercised without a real
PDF. It never puts a document into a chart -- that is the upload, which is the flow being
validated. Purge removes what it generated: the files, the documents uploaded from them, and the
lab rows those documents produced, so a citation never outlives the page it points at.

Needs OE_DOCTOR_PASS. The flag must be on for this instance (COPILOT_DEMO_TOOLS), or the actions
refuse and these cases skip.
"""

import pytest

import test_uc_copilot as uc
import test_uc_document_writer as w
from conftest import db_query

VARIANTS = ["abnormal", "normal", "unreadable"]


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
    # Nothing was in the chart, so nothing in the chart was touched.
    after = db_query(f"SELECT COUNT(*) FROM documents WHERE foreign_id = {w.IN_PANEL} AND deleted = 0")[0][0]
    assert after == before
