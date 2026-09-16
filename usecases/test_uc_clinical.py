"""UC1-UC8: the questions a clinician or clinical agent would ask about one patient."""

import pytest

from conftest import FHIR, REST, db_query


@pytest.fixture(scope="module")
def chosen_patient():
    """Pick the patient with the richest chart so every use case has data to find."""
    rows = db_query("""
        SELECT p.fname, p.lname, p.DOB,
               (SELECT COUNT(*) FROM form_encounter e WHERE e.pid = p.pid) AS enc,
               (SELECT COUNT(*) FROM lists l WHERE l.pid = p.pid AND l.type = 'medical_problem') AS prob,
               (SELECT COUNT(*) FROM prescriptions r WHERE r.patient_id = p.pid) AS rx,
               (SELECT COUNT(*) FROM form_vitals v WHERE v.pid = p.pid) AS vit
        FROM patient_data p
        ORDER BY (prob > 0) + (rx > 0) + (vit > 0) DESC, enc DESC
        LIMIT 1
    """)
    assert rows, "no patients in the database; run the Synthea import first"
    fname, lname, dob, *_ = rows[0]
    return {"given": fname, "family": lname, "birthDate": dob}


def bundle(resp) -> list[dict]:
    assert resp.status_code == 200, f"{resp.url} -> {resp.status_code} {resp.text[:300]}"
    body = resp.json()
    assert body["resourceType"] == "Bundle"
    return [e["resource"] for e in body.get("entry", [])]


@pytest.fixture(scope="module")
def patient_uuid(api, chosen_patient):
    """UC1 doubles as setup: find the patient the way an agent would, by name."""
    found = bundle(api.get(f"{FHIR}/Patient", params={
        "family": chosen_patient["family"], "given": chosen_patient["given"],
    }))
    match = [
        p for p in found
        if p.get("birthDate") == chosen_patient["birthDate"]
        and any(n.get("family") == chosen_patient["family"] for n in p.get("name", []))
    ]
    assert len(match) == 1, f"expected one match for {chosen_patient}, got {len(match)}"
    return match[0]["id"]


def test_uc1_find_patient_by_name(patient_uuid):
    assert len(patient_uuid) == 36  # FHIR ids here are UUIDs


def test_uc2_problem_list(api, patient_uuid):
    conditions = bundle(api.get(f"{FHIR}/Condition", params={"patient": patient_uuid}))
    assert conditions, "patient has no conditions"
    for c in conditions:
        assert c["subject"]["reference"] == f"Patient/{patient_uuid}"
        assert c.get("code"), f"condition {c['id']} has no code"


def test_uc3_medications(api, patient_uuid):
    meds = bundle(api.get(f"{FHIR}/MedicationRequest", params={"patient": patient_uuid}))
    assert meds, "patient has no medication requests"
    for m in meds:
        assert m["subject"]["reference"] == f"Patient/{patient_uuid}"


def test_uc4_allergies(api, patient_uuid):
    # Many synthetic patients have no allergies; a valid, correctly scoped Bundle is the check.
    for a in bundle(api.get(f"{FHIR}/AllergyIntolerance", params={"patient": patient_uuid})):
        assert a["patient"]["reference"] == f"Patient/{patient_uuid}"


def test_uc5_latest_vitals(api, patient_uuid):
    vitals = bundle(api.get(f"{FHIR}/Observation", params={
        "patient": patient_uuid, "category": "vital-signs",
    }))
    assert vitals, "patient has no vital-signs observations"
    for v in vitals:
        assert v["subject"]["reference"] == f"Patient/{patient_uuid}"
        assert v.get("effectiveDateTime"), f"observation {v['id']} has no date"
        # Panels (e.g. LOINC 85353-1) carry no value of their own; they group readings via hasMember.
        assert any(k in v for k in ("valueQuantity", "component", "dataAbsentReason", "hasMember")), \
            f"observation {v['id']} has no value, components, or members"
    readings = [v for v in vitals if "valueQuantity" in v]
    assert readings, "no vital sign carries an actual measured value"


def test_uc6_visit_history(api, patient_uuid):
    encounters = bundle(api.get(f"{FHIR}/Encounter", params={"patient": patient_uuid}))
    assert encounters, "patient has no encounters"
    for e in encounters:
        assert e["subject"]["reference"] == f"Patient/{patient_uuid}"
        assert e.get("period", {}).get("start"), f"encounter {e['id']} has no start date"


def test_uc7_immunizations(api, patient_uuid):
    for i in bundle(api.get(f"{FHIR}/Immunization", params={"patient": patient_uuid})):
        assert i["patient"]["reference"] == f"Patient/{patient_uuid}"


def test_uc8_rest_and_fhir_agree(api, patient_uuid):
    rest = api.get(f"{REST}/patient/{patient_uuid}")
    assert rest.status_code == 200, f"{rest.status_code} {rest.text[:300]}"
    r = rest.json()["data"]

    fhir = api.get(f"{FHIR}/Patient/{patient_uuid}")
    assert fhir.status_code == 200, f"{fhir.status_code} {fhir.text[:300]}"
    f = fhir.json()

    assert r["uuid"] == f["id"]
    assert r["DOB"] == f["birthDate"]
    assert any(n.get("family") == r["lname"] for n in f["name"])
