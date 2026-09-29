"""UC-PATIENT-TAB: the Co-Pilot tab inside the patient record (Week 2, stage 0).

The Week 1 tab lists the hospitalist's rounding list, so a patient outside the panel could
never be picked. Inside the patient record, OpenEMR has already opened whatever chart the
user chose (AUDIT.md S3: provider assignment is not an access restriction), so the panel
check is now the only barrier. These cases exercise it from that entry point.

Physician cases need OE_DOCTOR_PASS (doctor1). The agent service is only needed for the
last case, which skips if it refuses the session.

    $env:OPENEMR_BASE_URL="https://localhost:9300"; $env:OE_PASS="pass"; $env:OE_DOCTOR_PASS="<doctor1 pw>"
    .venv\\Scripts\\python -m pytest test_uc_patient_tab.py
"""

import base64
import re

import pytest
import requests

import test_uc_copilot as uc
from conftest import BASE_URL, OE_PASS, db_query

PATIENT_PAGE = f"{uc.MODULE}/patient.php"
API = f"{uc.MODULE}/api.php"
DEMOGRAPHICS = f"{BASE_URL}/interface/patient_file/summary/demographics.php"

# scripts/seed_patients assigns pids 1-25 to doctor1 (users.id 8) and 26-50 to doctor2 (id 9).
IN_PANEL = 3
OUT_OF_PANEL = 30


def set_active_patient(session: requests.Session, pid: int) -> str:
    """Open the chart the way the UI does, which stores pid in the session. Returns the page."""
    resp = session.get(f"{DEMOGRAPHICS}?set_pid={pid}", timeout=120)
    assert resp.status_code == 200, f"could not open patient {pid}: {resp.status_code}"
    return resp.text


@pytest.fixture(scope="module")
def admin():
    return uc.ui_login("admin", OE_PASS)


@pytest.fixture(scope="module")
def doctor():
    if not uc.DOCTOR_PASS:
        pytest.skip("OE_DOCTOR_PASS not set")
    return uc.ui_login("doctor1", uc.DOCTOR_PASS)


# --- the tab is offered in the patient record, to hospitalists only -----------

def test_patient_record_offers_the_copilot_tab_to_a_physician(doctor):
    page = set_active_patient(doctor, IN_PANEL)
    assert 'id="copilot"' in page, "the patient navbar has no Co-Pilot entry"
    assert "oe-module-copilot-agent/public/patient.php" in page


def test_the_copilot_entry_opens_a_tab_of_its_own_not_the_chart_view(doctor):
    """Clicking it must not replace the chart the clinician is reading. The navbar renderer drops
    `target` and emits the click handler verbatim, so the handler is where this is asserted."""
    page = set_active_patient(doctor, IN_PANEL)
    anchor = re.search(r'<li[^>]*id="copilot"[^>]*>\s*<a[^>]*>', page)
    assert anchor, "no anchor rendered for the Co-Pilot entry"
    markup = anchor.group(0)
    assert "top.navigateTab(" in markup and "'cpapat'" in markup, markup
    assert "top.activateTabByName('cpapat', true)" in markup, markup
    assert "return false" in markup, "the anchor would still navigate the chart view"
    assert '"' not in markup.split('onclick="', 1)[1].split('"', 1)[0], "a quote in the handler would break the attribute"


def test_patient_record_does_not_offer_the_tab_to_admin(admin):
    page = set_active_patient(admin, IN_PANEL)
    assert 'id="copilot"' not in page


# --- the page enforces role and scope from the session pid --------------------

def test_tab_without_an_active_patient_asks_for_one():
    if not uc.DOCTOR_PASS:
        pytest.skip("OE_DOCTOR_PASS not set")
    fresh = uc.ui_login("doctor1", uc.DOCTOR_PASS)   # a new session holds no pid
    page = fresh.get(PATIENT_PAGE, timeout=60).text
    assert "No patient selected" in page
    assert 'var CSRF' not in page, "the co-pilot must not start without a patient"


def test_in_panel_patient_renders_the_copilot(doctor):
    set_active_patient(doctor, IN_PANEL)
    page = doctor.get(PATIENT_PAGE, timeout=60).text
    # The JS state-label map contains the words "Access denied"; the refusal itself is an alert.
    assert "alert-danger" not in page
    assert re.search(r'var PID = 3;', page), "the page must carry the session pid, not a query parameter"
    assert re.search(r'var CSRF = "[0-9a-f]+"', page)


def test_out_of_panel_patient_is_refused_and_audited(doctor):
    set_active_patient(doctor, OUT_OF_PANEL)
    page = doctor.get(PATIENT_PAGE, timeout=60).text
    assert "Access denied" in page and "not assigned to you" in page
    assert 'var CSRF' not in page, "no co-pilot session may start for an out-of-panel patient"

    rows = db_query(
        "SELECT event, patient_id, success, comments FROM log "
        "WHERE event = 'copilot-scope-denied' AND user = 'doctor1' ORDER BY id DESC LIMIT 1"
    )
    assert rows, "the denial was not written to the audit log"
    event, patient_id, success, comments = rows[0]
    assert patient_id == str(OUT_OF_PANEL) and success == "0"
    # EventAuditLogger stores comments base64-encoded.
    decoded = base64.b64decode(comments).decode("utf-8", "replace")
    assert "entry=patient" in decoded, f"the audit row should say which entry point refused: {decoded}"


def test_gateway_refuses_the_same_pid_in_patient_context(doctor):
    csrf = uc.csrf_from_page(doctor)
    resp = doctor.post(f"{API}?action=open_patient&context=patient", json={"pid": OUT_OF_PANEL},
                       headers={"X-Copilot-Csrf": csrf}, timeout=60)
    assert resp.status_code == 403
    body = resp.json()
    assert body["state"] == "access_denied" and "not assigned to you" in body["reason"]


def test_admin_is_denied_on_the_patient_tab(admin):
    set_active_patient(admin, IN_PANEL)
    page = admin.get(PATIENT_PAGE, timeout=60).text
    assert "Access denied" in page and "Physicians group" in page


# --- the patient session is its own agent session ------------------------------

def test_open_patient_returns_that_patient_only_and_keeps_its_own_session(doctor):
    csrf = uc.csrf_from_page(doctor)
    headers = {"X-Copilot-Csrf": csrf}
    resp = doctor.post(f"{API}?action=open_patient&context=patient", json={"pid": IN_PANEL},
                       headers=headers, timeout=120)
    body = resp.json()
    if resp.status_code == 503:
        assert body["state"] == "unable_to_answer" and "patient" not in body
        pytest.skip(f"agent refused the session (fail closed): {body.get('reason')}")
    assert resp.status_code == 200, body
    assert body["patient"]["pid"] == IN_PANEL
    assert not re.search(r"\d", body["patient"]["name"])

    status = doctor.get(f"{API}?action=status&context=patient", headers=headers, timeout=60).json()
    assert [p["pid"] for p in status["patients"]] == [IN_PANEL]

    # The rounding-list session lives under a different id, so opening a patient never
    # replaces it. Without a rounds session, status in that context reports none.
    rounds = doctor.get(f"{API}?action=status", headers=headers, timeout=60)
    assert rounds.status_code in (200, 503)
    if rounds.status_code == 200:
        assert [p["pid"] for p in rounds.json().get("patients", [])] != [IN_PANEL]
