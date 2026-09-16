from datetime import date

from copilot import normalize
from copilot.schemas import Medication


def test_medication_status_comes_from_end_date_not_active_flag(today):
    ended_but_flagged = Medication(source_id="prescription:1", drug="x", end_date="2024-01-24", active=1)
    status, note = normalize.medication_status(ended_but_flagged, today)
    assert status == "ended"
    assert "uncertain" in note

    open_ended = Medication(source_id="prescription:2", drug="y", end_date=None, active=1)
    assert normalize.medication_status(open_ended, today)[0] == "active"

    future_end = Medication(source_id="prescription:3", drug="z", end_date="2027-01-01", active=1)
    assert normalize.medication_status(future_end, today)[0] == "active"


def test_problem_kind_and_clean_title():
    assert normalize.problem_kind("Essential hypertension (disorder)") == "disorder"
    assert normalize.problem_kind("Full-time employment (finding)") == "finding"
    assert normalize.clean_title("Medication review due (situation)") == "Medication review due"


def test_active_disorders_exclude_findings_and_resolved(chart101, today):
    titles = [normalize.clean_title(p.title) for p in normalize.active_problems(chart101, today)]
    assert titles == ["Diabetes mellitus type 2", "Essential hypertension"]


def test_reference_flagging_uses_demo_table_and_labels_it(chart101):
    potassium = next(lab for lab in chart101.labs if lab.source_id == "lab:6001")
    flag = normalize.flag_against_reference(potassium)
    assert flag.outcome == "out_of_range" and flag.direction == "high"
    assert "demo reference" in flag.reference and "not from the record" in flag.reference

    phq = next(lab for lab in chart101.labs if lab.source_id == "lab:6005")
    assert normalize.flag_against_reference(phq).outcome == "not_evaluated"


def test_recent_labs_fall_back_to_latest_collection_when_window_empty(chart101):
    flags, labs, window = normalize.recent_lab_flags(chart101, date(2027, 9, 15), 30)
    assert labs and all(lab.date == "2026-08-16" for lab in labs)
    assert "no results in the last 30 days" in window


def test_compliance_signals_are_cited(chart101, today):
    signals = normalize.compliance_signals(chart101, today)
    kinds = {s.kind for s in signals}
    assert {"review_due", "medication_status_uncertain", "immunization_gap"} <= kinds
    assert all(s.source_ids for s in signals)


def test_primary_diagnosis_matches_last_encounter_reason(chart101, today):
    problem, basis, extra = normalize.primary_diagnosis_candidate(chart101, today)
    assert problem.source_id == "problem:9001"
    assert "most recent encounter" in basis and extra == ["encounter:3001"]


def test_display_name_strips_synthea_suffixes():
    assert normalize.display_name("Judie557 Abernathy524") == "Judie Abernathy"


def test_strength_parsing():
    assert normalize.strength_mg("Acetaminophen 325 MG Oral Tablet") == 325
    assert normalize.strength_mg("Nitroglycerin 0.4 MG/ACTUAT Mucosal Spray") is None
