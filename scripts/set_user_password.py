"""Set a user's password through the user-administration form (admin re-authenticates).

Posts mode=update to interface/usergroup/usergroup_admin.php, the same request the
admin UI sends, so AuthUtils::updatePassword() enforces the password policy and the
change is audited. The update handler also rewrites authorized/active/calendar/see_auth
from the POST, so the current values are read from the edit form first and re-sent.

Usage:
    python set_user_password.py <base_url> <username> <admin_password_env> <new_password_env>

The passwords are read from the named environment variables, never from argv, so they
do not land in shell history:

    $env:OE_PASS="<admin pw>"; $env:OE_DOCTOR_PASS="<new pw>"
    python set_user_password.py https://localhost:9300 doctor1 OE_PASS OE_DOCTOR_PASS
"""

import os
import re
import sys
from pathlib import Path

import requests
import urllib3

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "usecases"))
from conftest import db_query  # noqa: E402

urllib3.disable_warnings()

BASE, USERNAME = sys.argv[1].rstrip("/"), sys.argv[2]
ADMIN_PASS, NEW_PASS = os.environ[sys.argv[3]], os.environ[sys.argv[4]]


def login() -> requests.Session:
    session = requests.Session()
    session.verify = False
    session.get(f"{BASE}/interface/login/login.php?site=default", timeout=60)
    resp = session.post(f"{BASE}/interface/main/main_screen.php?auth=login&site=default",
                        data={"new_login_session_management": "1", "authUser": "admin",
                              "clearPass": ADMIN_PASS, "languageChoice": "1"}, timeout=60)
    assert "clearPass" not in resp.text, "admin login failed"
    return session


def field(page: str, name: str) -> str:
    match = re.search(r"name=[\"']" + re.escape(name) + r"[\"'][^>]*value=[\"']([^\"']*)[\"']", page)
    return match.group(1) if match else ""


def checked(page: str, name: str) -> bool:
    match = re.search(r"name=[\"']" + re.escape(name) + r"[\"'][^>]*>", page)
    return bool(match and "checked" in match.group(0))


session = login()
safe_name = re.sub(r"[^A-Za-z0-9_.-]", "", USERNAME)
rows = db_query(f"SELECT id FROM users WHERE username = '{safe_name}'")
if not rows:
    sys.exit(f"no user named '{USERNAME}'")
user_id = rows[0][0]

# The update handler replaces ACL group membership with whatever access_group[] the POST
# carries; omitting it strips the user from every group and OpenEMR then refuses the login
# ("user not in any phpGACL groups"). Re-send the current groups.
groups = [row[0] for row in db_query(
    "SELECT g.name FROM gacl_aro a JOIN gacl_groups_aro_map m ON m.aro_id = a.id "
    f"JOIN gacl_aro_groups g ON g.id = m.group_id WHERE a.value = '{safe_name}'")]
assert groups, f"{USERNAME} is in no ACL group; fix that first (scripts/fix_acl.php)"

# The edit page is only served with a valid token in the URL (as the users list links it).
listing = session.get(f"{BASE}/interface/usergroup/usergroup_admin.php", timeout=60).text
list_token = field(listing, "csrf_token_form")
assert list_token, "no csrf_token_form on the users list page"
edit = session.get(f"{BASE}/interface/usergroup/user_admin.php?id={user_id}&csrf_token_form={list_token}", timeout=60).text
csrf = field(edit, "csrf_token_form")
assert csrf, "no csrf_token_form on the edit page"

form = {
    "csrf_token_form": csrf, "privatemode": "user_admin", "mode": "update", "id": user_id,
    "adminPass": ADMIN_PASS, "clearPass": NEW_PASS,
    "fname": field(edit, "fname"), "mname": field(edit, "mname"), "lname": field(edit, "lname"),
    "suffix": field(edit, "suffix"), "npi": field(edit, "npi"),
    "facility_id": field(edit, "facility_id") or "3", "billing_facility_id": field(edit, "billing_facility_id") or "3",
    "authorized": "1" if checked(edit, "authorized") else "", "active": "1" if checked(edit, "active") else "",
    "calendar": "1" if checked(edit, "calendar") else "", "see_auth": field(edit, "see_auth") or "1",
    "main_menu_role": field(edit, "main_menu_role") or "standard", "patient_menu_role": field(edit, "patient_menu_role") or "standard",
    "access_group[]": groups,
}
resp = session.post(f"{BASE}/interface/usergroup/usergroup_admin.php", data=form, timeout=120)
print(f"{USERNAME} (id {user_id}): POST status={resp.status_code}")
for pattern in (r"Password update error[^<]*", r"not long enough[^<]*", r"not strong enough[^<]*", r"Not authorized[^<]*", r"incorrect[^<]*"):
    found = re.search(pattern, resp.text, re.I)
    if found:
        print(f"  WARNING from app: {found.group(0)}")

# Verify by signing in as the user. A failed login answers with a script that sends the
# browser to login_screen.php?error=1, so check for that rather than for the form.
check = requests.Session()
check.verify = False
check.get(f"{BASE}/interface/login/login.php?site=default", timeout=60)
resp = check.post(f"{BASE}/interface/main/main_screen.php?auth=login&site=default",
                  data={"new_login_session_management": "1", "authUser": USERNAME, "clearPass": NEW_PASS, "languageChoice": "1"}, timeout=60)
failed = "login_screen.php?error=1" in resp.text or "clearPass" in resp.text
print("login check:", "FAILED" if failed else "OK")
after = [row[0] for row in db_query(
    "SELECT g.name FROM gacl_aro a JOIN gacl_groups_aro_map m ON m.aro_id = a.id "
    f"JOIN gacl_aro_groups g ON g.id = m.group_id WHERE a.value = '{safe_name}'")]
print("ACL groups after update:", after)
