"""Create provider accounts (doctor1, doctor2) through OpenEMR's user-administration form.

Posts to interface/usergroup/usergroup_admin.php with mode=new_user — the same
request the admin UI sends — so validation, UUID assignment, ACL group membership
and audit logging all run. No raw SQL.

Usage:
    python create_doctors.py <base_url> <admin_password> <doctor_password>

Examples:
    python create_doctors.py https://localhost:9300 pass 'SomeStrongPass!9'
    python create_doctors.py https://<app>.up.railway.app "$env:OE_PASS" 'SomeStrongPass!9'
"""

import re
import sys

import requests
import urllib3

urllib3.disable_warnings()

BASE, ADMIN_PASS, DOC_PASS = sys.argv[1].rstrip("/"), sys.argv[2], sys.argv[3]

# AclExtended::setUserAro() matches on the group TITLE ("Physicians"), not the
# gacl value ("doc"), and needs an array — hence access_group[] below. Sending a
# bare string raises "in_array(): Argument #2 must be of type array" and the
# request 500s *after* the user row is already inserted.
ACCESS_GROUP = "Physicians"
FACILITY_ID = "3"  # "Your Clinic Name Here" in a default install

DOCTORS = [
    {"username": "doctor1", "fname": "Dana", "lname": "Reyes", "npi": "1234567893"},
    {"username": "doctor2", "fname": "Samir", "lname": "Okafor", "npi": "1234567810"},
]


def login() -> requests.Session:
    session = requests.Session()
    session.verify = False
    session.get(f"{BASE}/interface/login/login.php?site=default", timeout=60)
    resp = session.post(
        f"{BASE}/interface/main/main_screen.php?auth=login&site=default",
        data={"new_login_session_management": "1", "authUser": "admin",
              "clearPass": ADMIN_PASS, "languageChoice": "1"},
        timeout=60, allow_redirects=True,
    )
    assert "clearPass" not in resp.text, "admin login failed"
    return session


def csrf_token(session: requests.Session) -> str:
    page = session.get(f"{BASE}/interface/usergroup/usergroup_admin_add.php", timeout=60).text
    match = re.search(r"name=[\"']csrf_token_form[\"']\s+value=[\"']([^\"']+)[\"']", page)
    assert match, "could not read csrf_token_form from the add-user page"
    return match.group(1)


def create(session: requests.Session, doctor: dict) -> None:
    form = {
        "csrf_token_form": csrf_token(session),
        "mode": "new_user",
        "rumple": doctor["username"],   # the form's username field
        "stiltskin": DOC_PASS,          # the new user's password
        "adminPass": ADMIN_PASS,        # admin re-authentication
        "fname": doctor["fname"],
        "mname": "",
        "lname": doctor["lname"],
        "suffix": "MD",
        "email": "",
        "authorized": "1",              # provider
        "calendar": "1",
        "facility_id": FACILITY_ID,
        "billing_facility_id": FACILITY_ID,
        "access_group[]": [ACCESS_GROUP],
        "groupname": "Default",
        "npi": doctor["npi"],
        "physician_type": "",
        "main_menu_role": "standard",
        "patient_menu_role": "standard",
        "see_auth": "1",
        "default_warehouse": "",
        "irnpool": "",
        "google_signin_email": "",
    }
    resp = session.post(f"{BASE}/interface/usergroup/usergroup_admin.php", data=form, timeout=120)
    print(f"{doctor['username']}: POST status={resp.status_code}")
    for pattern in (r"already exists", r"Password update error[^<]*", r"not long enough",
                    r"not strong enough", r"Not authorized"):
        found = re.search(pattern, resp.text)
        if found:
            print(f"  WARNING from app: {found.group(0)}")


session = login()
for doctor in DOCTORS:
    create(session, doctor)
print("done — verify ACL membership; if the POST returned 500, run fix_acl.php")
