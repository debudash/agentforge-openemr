"""Split the patient panel between doctor1 and doctor2 (first half / second half by pid).

Writes through PUT /api/patient/:puuid over OAuth, so OpenEMR's validation,
events and audit logging run. `providerID` persists through this route.

Reuses usecases/conftest.py for OAuth setup and database access, so the same
OE_DB_VIA switch selects the local docker stack or the Railway deployment.

Usage (local):
    cd usecases
    $env:OPENEMR_BASE_URL="https://localhost:9300"; $env:OE_PASS="pass"
    .venv\\Scripts\\python ..\\scripts\\assign_patients.py

Usage (Railway):
    $env:OPENEMR_BASE_URL="https://<app>.up.railway.app"; $env:OE_PASS="<admin pw>"
    $env:OE_DB_VIA="railway"; $env:OE_DB_PASS="<openemr db pw>"
    .venv\\Scripts\\python ..\\scripts\\assign_patients.py
"""

import sys
from pathlib import Path

import requests
import urllib3

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "usecases"))
from conftest import OAUTH, OE_PASS, OE_USER, READ_SCOPES, REST, _safe_id, db_query  # noqa: E402

urllib3.disable_warnings()
WRITE_SCOPES = READ_SCOPES + ["user/Patient.write", "user/patient.write"]

doctors = {row[1]: row[0] for row in db_query(
    "SELECT id, username FROM users WHERE username IN ('doctor1','doctor2') ORDER BY username"
)}
assert set(doctors) == {"doctor1", "doctor2"}, f"expected both doctors, got {doctors}"
print(f"doctor ids: {doctors}")

patients = db_query(
    "SELECT pid, LOWER(CONCAT(SUBSTR(HEX(uuid),1,8),'-',SUBSTR(HEX(uuid),9,4),'-',SUBSTR(HEX(uuid),13,4),"
    "'-',SUBSTR(HEX(uuid),17,4),'-',SUBSTR(HEX(uuid),21))) FROM patient_data ORDER BY pid"
)
print(f"patients: {len(patients)}")
assert len(patients) >= 2, "no patients found"

half = len(patients) // 2
plan = [(uuid, doctors["doctor1"]) for _, uuid in patients[:half]]
plan += [(uuid, doctors["doctor2"]) for _, uuid in patients[half:]]

client = requests.post(f"{OAUTH}/registration", verify=False, timeout=60, json={
    "application_type": "private", "redirect_uris": ["https://client.example.org/callback"],
    "client_name": "provider-assignment", "token_endpoint_auth_method": "client_secret_post",
    "contacts": ["admin@example.org"], "scope": " ".join(WRITE_SCOPES),
}).json()
cid = _safe_id(client["client_id"])
db_query(f"UPDATE oauth_clients SET is_enabled = 1 WHERE client_id = '{cid}'")

try:
    token = requests.post(f"{OAUTH}/token", verify=False, timeout=60, data={
        "grant_type": "password", "client_id": cid, "client_secret": client.get("client_secret", ""),
        "user_role": "users", "username": OE_USER, "password": OE_PASS,
        "scope": " ".join(WRITE_SCOPES),
    }).json()["access_token"]
    session = requests.Session()
    session.verify = False
    session.headers.update({"Authorization": f"Bearer {token}", "Content-Type": "application/json"})

    failures = []
    for index, (uuid, provider_id) in enumerate(plan, start=1):
        resp = session.put(f"{REST}/patient/{uuid}", json={"providerID": provider_id}, timeout=90)
        if resp.status_code != 200:
            failures.append((uuid, resp.status_code, resp.text[:120]))
        if index % 10 == 0:
            print(f"  {index}/{len(plan)} updated")
    print(f"updated {len(plan) - len(failures)}/{len(plan)}; failures={len(failures)}")
    for failure in failures[:5]:
        print(f"  FAILED {failure}")
finally:
    db_query(f"DELETE FROM api_token WHERE client_id = '{cid}'")
    db_query(f"DELETE FROM api_refresh_token WHERE client_id = '{cid}'")
    db_query(f"DELETE FROM oauth_clients WHERE client_id = '{cid}'")

print("--- verification ---")
for row in db_query(
    "SELECT COALESCE(u.username,'(unassigned)'), COUNT(*) FROM patient_data p "
    "LEFT JOIN users u ON u.id = p.providerID GROUP BY p.providerID ORDER BY 1"
):
    print(f"  {row[0]}: {row[1]}")
