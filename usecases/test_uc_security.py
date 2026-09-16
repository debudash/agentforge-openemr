"""UC9-UC10: access control holds at the API boundary."""

import requests

from conftest import FHIR


def test_uc9_no_token_is_rejected():
    resp = requests.get(f"{FHIR}/Patient", verify=False, timeout=30)
    assert resp.status_code == 401


def test_uc10_narrow_token_can_read_patients(narrow_api):
    resp = narrow_api.get(f"{FHIR}/Patient", params={"_count": 1})
    assert resp.status_code == 200, f"{resp.status_code} {resp.text[:300]}"


def test_uc10_narrow_token_cannot_read_conditions(narrow_api):
    resp = narrow_api.get(f"{FHIR}/Condition")
    assert resp.status_code in (401, 403), \
        f"token scoped to Patient.read reached Condition: {resp.status_code}"
