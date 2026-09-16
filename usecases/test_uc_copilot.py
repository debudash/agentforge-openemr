"""UC-COPILOT: the CopilotAgent tab and its JSON gateway (role enforcement, scope, states).

Runs against a live OpenEMR with the module registered. Role cases need only the admin
account. Physician cases need a provider password in OE_DOCTOR_PASS (doctor1) and are
skipped otherwise. The agent service does not need a model key for the denial and
configuration paths; with no key the gateway must fail closed.

    $env:OPENEMR_BASE_URL="https://localhost:9300"; $env:OE_PASS="pass"; $env:OE_DOCTOR_PASS="<doctor1 pw>"
    .venv\\Scripts\\python -m pytest test_uc_copilot.py
"""

import os
import re

import pytest
import requests

from conftest import BASE_URL, OE_PASS

MODULE = f"{BASE_URL}/interface/modules/custom_modules/oe-module-copilot-agent/public"
DOCTOR_PASS = os.environ.get("OE_DOCTOR_PASS")
# The demo books this many patients per doctor per day (scripts/seed_appointments.py).
DEMO_LIST_SIZE = int(os.environ.get("SEED_PER_DOCTOR", "5"))


def ui_login(username: str, password: str) -> requests.Session:
    session = requests.Session()
    session.verify = False
    session.get(f"{BASE_URL}/interface/login/login.php?site=default", timeout=60)
    resp = session.post(f"{BASE_URL}/interface/main/main_screen.php?auth=login&site=default",
                        data={"new_login_session_management": "1", "authUser": username, "clearPass": password, "languageChoice": "1"},
                        timeout=60)
    # A failed login answers with a script redirecting to login_screen.php?error=1.
    assert "login_screen.php?error=1" not in resp.text and "clearPass" not in resp.text, f"login failed for {username}"
    return session


def csrf_from_page(session: requests.Session) -> str:
    page = session.get(f"{MODULE}/index.php", timeout=60).text
    match = re.search(r'var CSRF = "([0-9a-f]+)"', page)
    assert match, "the tab page did not embed a CSRF token"
    return match.group(1)


@pytest.fixture(scope="module")
def admin():
    return ui_login("admin", OE_PASS)


@pytest.fixture(scope="module")
def doctor():
    if not DOCTOR_PASS:
        pytest.skip("OE_DOCTOR_PASS not set")
    return ui_login("doctor1", DOCTOR_PASS)


# --- role enforcement (PRD FR15, RBAC matrix) --------------------------------

def test_anonymous_cannot_reach_the_gateway():
    resp = requests.get(f"{MODULE}/api.php?action=open", verify=False, timeout=60, allow_redirects=False)
    # globals.php ends the request before the module runs: a redirect to login, a bare error (master
    # returns 400) or the stable image's "Site ID is missing from session data!" page, never content.
    assert (resp.status_code in (302, 400, 401, 403) or "login" in resp.text.lower()
            or "site id is missing" in resp.text.lower())
    assert "patients" not in resp.text and "correlation_id" not in resp.text


def test_admin_is_denied_by_default(admin):
    page = admin.get(f"{MODULE}/index.php", timeout=60).text
    assert "Access denied" in page and "Physicians group" in page
    resp = admin.get(f"{MODULE}/api.php?action=open", timeout=60)
    assert resp.status_code == 403
    body = resp.json()
    assert body["state"] == "access_denied" and "role not supported" in body["reason"]
    assert "patients" not in body and re.fullmatch(r"[0-9a-f-]{36}", body["correlation_id"])


def test_post_without_csrf_is_rejected_even_for_a_physician(doctor):
    resp = doctor.post(f"{MODULE}/api.php?action=select", json={"pid": 1}, timeout=60)
    assert resp.status_code == 403
    assert resp.json()["state"] in ("unable_to_answer", "access_denied")


# --- scope and states (REQ-SCOPE-1, FR17, FR20) -------------------------------

def test_physician_open_returns_only_todays_scoped_list(doctor):
    csrf = csrf_from_page(doctor)
    resp = doctor.get(f"{MODULE}/api.php?action=open", headers={"X-Copilot-Csrf": csrf}, timeout=120)
    body = resp.json()
    if resp.status_code == 503:
        # No model key on the agent service: the gateway must fail closed with a reason, never a partial list.
        assert body["state"] == "unable_to_answer" and "patients" not in body
        pytest.skip(f"agent refused the session (fail closed): {body.get('reason')}")
    assert resp.status_code == 200, body
    assert body["patients"], "no appointments booked for doctor1 today; run scripts/seed_appointments.py"
    assert len(body["patients"]) <= DEMO_LIST_SIZE, f"the demo rounding list is {DEMO_LIST_SIZE} patients per doctor"
    for patient in body["patients"]:
        assert set(patient["sources"]) >= {"problems", "medications", "allergies", "labs", "encounters"}
        assert not re.search(r"\d", patient["name"]), "Synthea numeric suffixes must be stripped"


def test_physician_cannot_select_a_patient_outside_the_panel(doctor):
    csrf = csrf_from_page(doctor)
    # doctor2's patients are the upper half of the pid range; pick the highest pid.
    other = requests.get(f"{BASE_URL}/apis/default/fhir/metadata", verify=False, timeout=30)  # keep-alive sanity
    assert other.status_code == 200
    resp = doctor.post(f"{MODULE}/api.php?action=select", json={"pid": 999999}, headers={"X-Copilot-Csrf": csrf}, timeout=60)
    assert resp.status_code == 403
    body = resp.json()
    assert body["state"] == "access_denied" and "not on your rounding list" in body["reason"]
