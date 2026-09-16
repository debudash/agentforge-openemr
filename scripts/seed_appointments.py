"""Book today's rounding list: N appointments per doctor, through the REST API.

The co-pilot's rounding list is "today's appointments booked for the signed-in
provider, restricted to that provider's assigned patients". The Synthea dataset has
no calendar events, so this books them. Writes go through
POST /api/patient/:pid/appointment so validation and audit logging run (AUDIT C1b).

Idempotent per day: existing co-pilot appointments for today are deleted first
(only those titled "Rounding (co-pilot demo)"), then re-created at 08:00, 08:15, ...

Usage (local):
    cd usecases
    $env:OPENEMR_BASE_URL="https://localhost:9300"; $env:OE_PASS="pass"
    .venv\\Scripts\\python ..\\scripts\\seed_appointments.py            # 12 per doctor
    .venv\\Scripts\\python ..\\scripts\\seed_appointments.py --per-doctor 6

Usage (Railway): add $env:OE_DB_VIA="railway"; $env:OE_DB_PASS="<openemr db pw>"
"""

import argparse
import datetime as dt
import sys
from pathlib import Path

import requests
import urllib3

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "usecases"))
from conftest import OAUTH, OE_PASS, OE_USER, READ_SCOPES, REST, _safe_id, db_query  # noqa: E402

urllib3.disable_warnings()
TITLE = "Rounding (co-pilot demo)"
SCOPES = READ_SCOPES + ["user/appointment.read", "user/appointment.write"]

parser = argparse.ArgumentParser()
parser.add_argument("--per-doctor", type=int, default=12)
parser.add_argument("--date", default=None, help="YYYY-MM-DD; default is the OpenEMR server's current date")
parser.add_argument("--category", type=int, default=5, help="pc_catid (5 = Office Visit)")
args = parser.parse_args()
if args.date is None:
    # The co-pilot lists appointments for the *server's* today (the container runs on UTC),
    # which can differ from the host's local date late in the day.
    args.date = db_query("SELECT CURDATE()")[0][0]
    print(f"server date: {args.date}")

doctors = {row[1]: int(row[0]) for row in db_query(
    "SELECT id, username FROM users WHERE username IN ('doctor1','doctor2') ORDER BY username")}
assert set(doctors) == {"doctor1", "doctor2"}, f"expected both doctors, got {doctors}"
facility = int(db_query("SELECT id FROM facility ORDER BY id LIMIT 1")[0][0])

# Remove this script's earlier bookings for the date, so re-running moves the list to today.
removed = db_query(
    f"SELECT COUNT(*) FROM openemr_postcalendar_events WHERE pc_title = '{TITLE}' AND pc_eventDate = '{args.date}'")[0][0]
db_query(f"DELETE FROM openemr_postcalendar_events WHERE pc_title = '{TITLE}' AND pc_eventDate = '{args.date}'")
print(f"removed {removed} existing '{TITLE}' appointment(s) on {args.date}")

client = requests.post(f"{OAUTH}/registration", verify=False, timeout=60, json={
    "application_type": "private", "redirect_uris": ["https://client.example.org/callback"],
    "client_name": "copilot-appointment-seeder", "token_endpoint_auth_method": "client_secret_post",
    "contacts": ["admin@example.org"], "scope": " ".join(SCOPES),
}).json()
cid = _safe_id(client["client_id"])
db_query(f"UPDATE oauth_clients SET is_enabled = 1 WHERE client_id = '{cid}'")

try:
    token = requests.post(f"{OAUTH}/token", verify=False, timeout=60, data={
        "grant_type": "password", "client_id": cid, "client_secret": client.get("client_secret", ""),
        "user_role": "users", "username": OE_USER, "password": OE_PASS, "scope": " ".join(SCOPES),
    }).json()["access_token"]
    session = requests.Session()
    session.verify = False
    session.headers.update({"Authorization": f"Bearer {token}", "Content-Type": "application/json"})

    total = 0
    for username, uid in doctors.items():
        pids = [int(r[0]) for r in db_query(
            f"SELECT pid FROM patient_data WHERE providerID = {uid} ORDER BY pid LIMIT {args.per_doctor}")]
        slot = dt.datetime.fromisoformat(f"{args.date}T08:00")
        booked = 0
        for pid in pids:
            resp = session.post(f"{REST}/patient/{pid}/appointment", timeout=60, json={
                "pc_catid": args.category, "pc_title": TITLE, "pc_duration": 900,
                "pc_hometext": "Booked by scripts/seed_appointments.py for the co-pilot demo",
                "pc_apptstatus": "-", "pc_eventDate": args.date, "pc_startTime": slot.strftime("%H:%M"),
                "pc_facility": facility, "pc_billing_location": facility, "pc_aid": uid,
            })
            if resp.status_code == 200:
                booked += 1
            else:
                print(f"  FAILED pid={pid}: {resp.status_code} {resp.text[:160]}")
            slot += dt.timedelta(minutes=15)
        print(f"{username} (id {uid}): booked {booked}/{len(pids)}")
        total += booked
    print(f"total booked: {total}")
finally:
    db_query(f"DELETE FROM api_token WHERE client_id = '{cid}'")
    db_query(f"DELETE FROM api_refresh_token WHERE client_id = '{cid}'")
    db_query(f"DELETE FROM oauth_clients WHERE client_id = '{cid}'")

print("--- verification ---")
for row in db_query(
    f"SELECT u.username, COUNT(*) FROM openemr_postcalendar_events e JOIN users u ON u.id = e.pc_aid "
    f"WHERE e.pc_eventDate = '{args.date}' AND e.pc_title = '{TITLE}' GROUP BY u.username ORDER BY 1"):
    print(f"  {row[0]}: {row[1]} appointment(s) on {args.date}")
