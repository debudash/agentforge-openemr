from copilot import constraints
from copilot.reference_data import RULES_VERSION


def by_id(outcomes, rule_id):
    return next(o for o in outcomes if o.rule_id == rule_id)


def test_allergy_conflict_flags_penicillin_against_recorded_allergy(chart101, today):
    outcome = constraints.allergy_conflict(chart101, today)
    assert outcome.outcome == "flag"
    assert {"prescription:7004", "allergy:8001"} <= set(outcome.source_ids)
    assert "prescription:7003" not in outcome.source_ids  # amoxicillin ended: not an active conflict


def test_interaction_pair_flagged_only_among_active_medications(chart101, today):
    outcome = constraints.drug_interaction(chart101, today)
    assert outcome.outcome == "flag" and "IX-2" in outcome.summary
    assert {"prescription:7001", "prescription:7002"} <= set(outcome.source_ids)


def test_dose_threshold_pass_and_unable(chart101, today):
    outcome = constraints.dosage_threshold(chart101, today)
    assert outcome.outcome == "pass"
    assert "2600 mg/day within" in outcome.summary


def test_dose_threshold_unable_when_inputs_missing(chart101, today):
    for med in chart101.medications:
        if med.source_id == "prescription:7005":
            med.interval = None
    outcome = constraints.dosage_threshold(chart101, today)
    assert outcome.outcome == "unable_to_evaluate"
    assert "frequency=not recorded" in outcome.summary


def test_dose_threshold_flag_when_exceeded(chart101, today):
    for med in chart101.medications:
        if med.source_id == "prescription:7005":
            med.dosage = "4"   # 325 * 4 * 4 = 5200 mg/day
    outcome = constraints.dosage_threshold(chart101, today)
    assert outcome.outcome == "flag" and "exceeds" in outcome.summary


def test_lab_range_flags_but_never_grades_severity(chart101, today):
    outcome = constraints.laboratory_range(chart101, today, 180)
    assert outcome.outcome == "flag"
    assert "Potassium" in outcome.summary and "Glucose" in outcome.summary
    assert "critical" not in outcome.summary.lower()


def test_lab_rule_unable_when_source_failed(chart303, today):
    outcome = constraints.laboratory_range(chart303, today, 180)
    assert outcome.outcome == "unable_to_evaluate"


def test_medication_status_rule_flags_uncertain(chart101, today):
    outcome = constraints.medication_status_rule(chart101, today)
    assert outcome.outcome == "flag" and "prescription:7003" in outcome.source_ids


def test_engine_failure_is_disclosed_not_raised(chart101, today, monkeypatch):
    def boom(*_args, **_kwargs):
        raise RuntimeError("table missing")

    monkeypatch.setattr(constraints, "drug_interaction", boom)
    outcomes = constraints.run_all(chart101, today)
    assert by_id(outcomes, "INTERACTION-1").outcome == "engine_failure"
    assert all(o.rule_version == RULES_VERSION for o in outcomes)
    assert len(outcomes) == 5
