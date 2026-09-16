"""UC0: the Synthea sample data is actually loaded."""

from conftest import db_query


def count(sql: str) -> int:
    return int(db_query(sql)[0][0])


def test_at_least_50_patients():
    assert count("SELECT COUNT(*) FROM patient_data") >= 50


def test_every_patient_has_a_uuid():
    # APIs address patients by UUID; a missing one makes the patient unreachable.
    assert count("SELECT COUNT(*) FROM patient_data WHERE uuid IS NULL") == 0


def test_encounters_loaded():
    assert count("SELECT COUNT(*) FROM form_encounter") > 0


def test_problems_loaded():
    assert count("SELECT COUNT(*) FROM lists WHERE type = 'medical_problem'") > 0


def test_medications_loaded():
    rx = count("SELECT COUNT(*) FROM prescriptions")
    med_list = count("SELECT COUNT(*) FROM lists WHERE type = 'medication'")
    assert rx + med_list > 0


def test_vitals_loaded():
    assert count("SELECT COUNT(*) FROM form_vitals") > 0
