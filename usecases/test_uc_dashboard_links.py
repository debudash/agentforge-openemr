"""UC-DASHBOARD-LINKS: the new dashboard's Co-Pilot and Demo Data links (ADR 0006, spec 12.1).

The new dashboard has no PHP session of its own; its patient comes from the SMART launch as a
FHIR id. Its header links to the module pages with `?patient=<FHIR uuid>&site=<site>`. The module
page resolves the uuid and refuses unless it is the patient the OpenEMR session has open, so a
link can never show one patient's co-pilot under another patient's name. The refusal path is
tested as hard as the acceptance path: every way the link can be wrong must end in a refusal
that starts nothing and shows no chart data.

    $env:OE_DOCTOR_PASS="<doctor1 pw>"; .venv\\Scripts\\python -m pytest test_uc_dashboard_links.py
"""

import base64
import json
import re
from pathlib import Path

import pytest
import requests

import test_uc_copilot as uc
from conftest import db_query

PAGES = ["patient.php", "demo.php"]
DEMOGRAPHICS = f"{uc.BASE_URL}/interface/patient_file/summary/demographics.php"

# scripts/seed_patients assigns pids 1-25 to doctor1 and 26-50 to doctor2.
SESSION_PID = 3
OTHER_PID = 5
OUT_OF_PANEL = 30


def uuid_of(pid: int) -> str:
    rows = db_query(
        "SELECT LOWER(INSERT(INSERT(INSERT(INSERT(HEX(uuid),9,0,'-'),14,0,'-'),19,0,'-'),24,0,'-')) "
        f"FROM patient_data WHERE pid = {int(pid)}"
    )
    assert rows and rows[0][0], f"patient {pid} has no uuid"
    return rows[0][0]


def name_of(pid: int) -> str:
    rows = db_query(f"SELECT fname, lname FROM patient_data WHERE pid = {int(pid)}")
    return f"{rows[0][0]} {rows[0][1]}"


def session_pid(session: requests.Session) -> str:
    """The pid the OpenEMR session holds: the unchanged page (no parameter) prints it."""
    html = session.get(f"{uc.MODULE}/patient.php", timeout=60).text
    match = re.search(r"var PID = (\d+);", html)
    return match.group(1) if match else ""


def open_chart(session: requests.Session, pid: int) -> None:
    resp = session.get(f"{DEMOGRAPHICS}?set_pid={pid}", timeout=120)
    assert resp.status_code == 200


def link(page: str, patient: str) -> str:
    return f"{uc.MODULE}/{page}?patient={requests.utils.quote(patient, safe='')}&site=default"


def assert_nothing_started(html: str) -> None:
    """A refusal starts no co-pilot and carries no session patient's chart."""
    assert "var CSRF" not in html, "a refusal must not start a co-pilot session"
    assert "var PID" not in html, "a refusal must not carry a patient id to the client"
    assert "cpa-chat" not in html and "cpa-gen-form" not in html


@pytest.fixture()
def doctor():
    if not uc.DOCTOR_PASS:
        pytest.skip("OE_DOCTOR_PASS not set")
    s = uc.ui_login("doctor1", uc.DOCTOR_PASS)
    open_chart(s, SESSION_PID)
    return s


# --- acceptance ---------------------------------------------------------------

def test_no_parameter_behaves_as_today(doctor):
    html = doctor.get(f"{uc.MODULE}/patient.php", timeout=60).text
    assert re.search(r"var PID = 3;", html)
    assert "cpa-link-refused" not in html


def test_matching_uuid_renders_the_page_for_that_patient(doctor):
    resp = doctor.get(link("patient.php", uuid_of(SESSION_PID)), timeout=60)
    assert resp.status_code == 200
    assert re.search(r"var PID = 3;", resp.text)
    assert "cpa-link-refused" not in resp.text


def test_matching_uuid_is_case_insensitive(doctor):
    resp = doctor.get(link("patient.php", uuid_of(SESSION_PID).upper()), timeout=60)
    assert re.search(r"var PID = 3;", resp.text)


@pytest.mark.parametrize("page", PAGES)
def test_matching_uuid_is_not_refused_on_either_page(doctor, page):
    resp = doctor.get(link(page, uuid_of(SESSION_PID)), timeout=60)
    assert "cpa-link-refused" not in resp.text


# --- refusal ------------------------------------------------------------------

@pytest.mark.parametrize("page", PAGES)
def test_mismatched_uuid_is_refused_and_names_both_patients(doctor, page):
    resp = doctor.get(link(page, uuid_of(OTHER_PID)), timeout=60)
    assert resp.status_code == 409
    html = resp.text
    assert "cpa-link-refused" in html
    assert name_of(OTHER_PID) in html, "the refusal names the dashboard's patient"
    assert name_of(SESSION_PID) in html, "the refusal names the patient the session has open"
    assert_nothing_started(html)
    assert session_pid(doctor) == str(SESSION_PID), "a refused link must not change the open chart"


def test_mismatched_uuid_is_audited(doctor):
    before = int(db_query("SELECT IFNULL(MAX(id), 0) FROM log")[0][0])
    doctor.get(link("patient.php", uuid_of(OTHER_PID)), timeout=60)
    rows = db_query(
        "SELECT patient_id, success, comments FROM log "
        f"WHERE event = 'copilot-link-mismatch' AND user = 'doctor1' AND id > {before} ORDER BY id DESC LIMIT 1"
    )
    assert rows, "the mismatch was not written to the audit log"
    patient_id, success, comments = rows[0]
    assert patient_id == str(OTHER_PID) and success == "0"
    assert f"session_pid={SESSION_PID}" in base64.b64decode(comments).decode("utf-8", "replace")


@pytest.mark.parametrize("page", PAGES)
def test_unknown_uuid_is_refused(doctor, page):
    resp = doctor.get(link(page, "00000000-0000-4000-8000-000000000000"), timeout=60)
    assert resp.status_code == 404
    assert "cpa-link-refused" in resp.text and "No patient matches" in resp.text
    assert_nothing_started(resp.text)
    assert name_of(SESSION_PID) not in resp.text, "an unknown link says nothing about the open chart"


@pytest.mark.parametrize("value", [
    "3",                                            # a pid is not accepted in place of a uuid
    "not-a-uuid",
    "' OR '1'='1",
    "<script>alert(1)</script>",
    "a2bf78bb-8052-4600-a47f-567135c1f296x",
    "",
])
def test_malformed_patient_parameter_is_refused_without_reflecting_it(doctor, value):
    resp = doctor.get(link("patient.php", value), timeout=60)
    assert resp.status_code == 400
    assert "cpa-link-refused" in resp.text
    assert_nothing_started(resp.text)
    if len(value) > 3:
        assert value not in resp.text, "the raw parameter must not be echoed back"


def test_a_repeated_patient_parameter_is_refused(doctor):
    url = f"{uc.MODULE}/patient.php?patient={uuid_of(SESSION_PID)}&patient={uuid_of(OTHER_PID)}&site=default"
    resp = doctor.get(url, timeout=60)
    assert resp.status_code in (400, 409)
    assert_nothing_started(resp.text)


def test_no_session_shows_the_openemr_login(doctor):
    anonymous = requests.Session()
    anonymous.verify = False
    resp = anonymous.get(link("patient.php", uuid_of(SESSION_PID)), timeout=60)
    assert "login_screen.php" in resp.text or "login.php" in resp.url
    assert_nothing_started(resp.text)
    assert name_of(SESSION_PID) not in resp.text


# --- the offer to open the dashboard's patient --------------------------------

def refusal_form(html: str) -> dict:
    token = re.search(r'name="cpa_switch_token" value="([0-9a-f]+)"', html)
    assert token, "the refusal offers to open the dashboard's patient"
    return {"cpa_switch_token": token.group(1)}


def test_switch_opens_the_dashboards_patient_then_renders_it(doctor):
    target = uuid_of(OTHER_PID)
    html = doctor.get(link("patient.php", target), timeout=60).text
    resp = doctor.post(link("patient.php", target), data=refusal_form(html), timeout=60)
    assert resp.status_code == 200
    assert re.search(rf"var PID = {OTHER_PID};", resp.text), "after the switch the page is for the linked patient"
    assert session_pid(doctor) == str(OTHER_PID)


def test_switch_without_the_token_is_refused_and_changes_nothing(doctor):
    resp = doctor.post(link("patient.php", uuid_of(OTHER_PID)), data={"cpa_switch_token": "0" * 64}, timeout=60)
    assert resp.status_code == 403
    assert_nothing_started(resp.text)
    assert session_pid(doctor) == str(SESSION_PID)


def test_switch_token_from_another_session_is_refused(doctor):
    other = uc.ui_login("doctor1", uc.DOCTOR_PASS)
    open_chart(other, SESSION_PID)
    foreign = refusal_form(other.get(link("patient.php", uuid_of(OTHER_PID)), timeout=60).text)
    resp = doctor.post(link("patient.php", uuid_of(OTHER_PID)), data=foreign, timeout=60)
    assert resp.status_code == 403
    assert session_pid(doctor) == str(SESSION_PID)


def test_switch_does_not_bypass_the_panel_check(doctor):
    target = uuid_of(OUT_OF_PANEL)
    html = doctor.get(link("patient.php", target), timeout=60).text
    resp = doctor.post(link("patient.php", target), data=refusal_form(html), timeout=60)
    assert "not assigned to you" in resp.text
    assert "var CSRF" not in resp.text


def test_switch_to_an_unknown_uuid_is_refused(doctor):
    html = doctor.get(link("patient.php", uuid_of(OTHER_PID)), timeout=60).text
    form = refusal_form(html)
    resp = doctor.post(link("patient.php", "00000000-0000-4000-8000-000000000000"), data=form, timeout=60)
    assert resp.status_code == 404
    assert session_pid(doctor) == str(SESSION_PID)


# --- the dashboard's flag endpoint ---------------------------------------------

def test_flags_are_public_and_carry_no_patient_data():
    resp = requests.get(f"{uc.MODULE}/flags.php?site=default", verify=False, timeout=60)
    assert resp.status_code == 200
    body = resp.json()
    assert set(body) == {"demoTools"} and isinstance(body["demoTools"], bool)
    assert resp.headers.get("Cache-Control", "").startswith("no-store")


# --- a patient the user may not see is not named, and cannot be switched to ---------------

SQUAD_PID = 44
RESTRICTED = Path(__file__).resolve().parent.parent / "dashboard" / "e2e" / ".auth" / "restricted-users.json"


@pytest.fixture()
def squad_patient():
    """pid 44 in a squad no test user belongs to (ADR 0005, local stack only); restored after."""
    db_query(f"UPDATE patient_data SET squad = 'dashsquad' WHERE pid = {SQUAD_PID}")
    yield SQUAD_PID
    db_query(f"UPDATE patient_data SET squad = '' WHERE pid = {SQUAD_PID}")


@pytest.fixture()
def demo_viewer():
    if not RESTRICTED.exists():
        pytest.skip("restricted users not created (dashboard/e2e/setup/restricted-users.php)")
    password = json.loads(RESTRICTED.read_text())["dash-demoview"]
    s = uc.ui_login("dash-demoview", password)
    open_chart(s, SESSION_PID)
    return s


def test_a_link_to_a_patient_outside_the_users_squad_is_refused_without_naming_them(demo_viewer, squad_patient):
    resp = demo_viewer.get(link("patient.php", uuid_of(squad_patient)), timeout=60)
    assert resp.status_code == 403
    assert "cpa-link-refused" in resp.text
    assert name_of(squad_patient) not in resp.text, "a patient the user may not see must not be named"
    assert 'name="cpa_switch_token"' not in resp.text, "no offer to open a patient the user may not see"
    assert_nothing_started(resp.text)


def test_a_forged_switch_to_a_patient_outside_the_users_squad_changes_nothing(demo_viewer, squad_patient):
    # Even with a token computed for that patient (it is bound to the session key, which the
    # attacker would need), the switch must re-check that the user may see the patient.
    resp = demo_viewer.post(link("patient.php", uuid_of(squad_patient)), data={"cpa_switch_token": "0" * 64}, timeout=60)
    assert resp.status_code == 403
    html = demo_viewer.get(f"{DEMOGRAPHICS}", timeout=60).text
    assert name_of(squad_patient) not in html
