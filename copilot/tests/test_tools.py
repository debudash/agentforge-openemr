import json

from copilot.tools import ChartContext, make_tools


def tool(ctx, name):
    return next(t for t in make_tools(ctx) if t.name == name)


def test_tools_refuse_any_other_patient_without_revealing_existence(chart101, today):
    ctx = ChartContext(chart101, today)
    for name in ("get_problems", "get_labs", "get_medications", "get_allergies", "run_constraint_checks"):
        result = json.loads(tool(ctx, name).invoke({"pid": 202}))
        assert result["result"] == "denied"
        assert "records" not in result
    assert len(ctx.denials) == 5


def test_get_labs_filters_by_test_and_window(chart101, today):
    ctx = ChartContext(chart101, today)
    result = json.loads(tool(ctx, "get_labs").invoke({"pid": 101, "test": "potassium", "since_days": 420}))
    assert [r["source_id"] for r in result["records"]] == ["lab:6001", "lab:6007"]
    assert result["records"][0]["demo_reference_check"] == "out_of_range"

    windowed = json.loads(tool(ctx, "get_labs").invoke({"pid": 101, "test": "potassium", "since_days": 365}))
    assert [r["source_id"] for r in windowed["records"]] == ["lab:6001"]   # 2025-08-10 is 401 days old

    empty = json.loads(tool(ctx, "get_labs").invoke({"pid": 101, "test": "troponin"}))
    assert empty["result"] == "empty" and "most recent result" in empty["note"]


def test_failed_source_returns_error_not_empty(chart303, today):
    ctx = ChartContext(chart303, today)
    result = json.loads(tool(ctx, "get_labs").invoke({"pid": 303}))
    assert result["result"] == "error" and "do not infer" in result["note"]


def test_allergies_empty_note_forbids_no_known_allergies(chart202, today):
    ctx = ChartContext(chart202, today)
    result = json.loads(tool(ctx, "get_allergies").invoke({"pid": 202}))
    assert result["result"] == "empty" and "never 'no known allergies'" in result["note"]


def test_derived_records_carry_source_ids(chart101, today):
    ctx = ChartContext(chart101, today)
    rules = json.loads(tool(ctx, "run_constraint_checks").invoke({"pid": 101}))
    assert {r["source_id"] for r in rules["records"]} >= {"rule:ALLERGY-1", "rule:LAB-1"}
    signals = json.loads(tool(ctx, "get_compliance_signals").invoke({"pid": 101}))
    assert signals["records"][0]["source_id"] == "signal:1" and signals["records"][0]["based_on"]
