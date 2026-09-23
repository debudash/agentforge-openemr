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
    assert result["source_id"] == "empty:allergies" and "empty:allergies" in ctx.returned_ids


def test_numbers_from_the_question_are_allowed_in_the_answer(chart101, settings, today):
    """'Any labs in the last 30 days?' -> 'No lab results in the last 30 days' cites the empty lookup;
    the 30 is the clinician's own number, not a chart value."""
    from copilot.agent import answer_followup
    from copilot.llm import ScriptedLLM
    from copilot.schemas import AnswerDraft, Claim, ResponseState
    from langchain_core.messages import AIMessage
    lookup = AIMessage(content="", tool_calls=[{"name": "get_labs", "args": {"pid": 101, "since_days": 30}, "id": "c1", "type": "tool_call"}])
    final = AnswerDraft(claims=[Claim(text="No lab results are recorded in the last 30 days; the most recent is dated 2026-08-16.", source_ids=["empty:labs"])])
    response, _ = answer_followup(chart101, "Any lab results in the last 30 days?", [], ScriptedLLM([lookup, final]), settings, "cid-30", __import__("datetime").date(2027, 9, 15))
    assert response.state == ResponseState.COMPLETE and len(response.claims) == 1, response.removed_claims


def test_none_recorded_claim_can_cite_the_empty_result(chart202, settings, today):
    """'No allergies are recorded' cites empty:allergies and verifies; a fabricated id would not."""
    from copilot.agent import answer_followup
    from copilot.llm import ScriptedLLM
    from copilot.schemas import AnswerDraft, Claim, ResponseState
    from langchain_core.messages import AIMessage
    lookup = AIMessage(content="", tool_calls=[{"name": "get_allergies", "args": {"pid": 202}, "id": "c1", "type": "tool_call"}])
    final = AnswerDraft(claims=[Claim(text="No allergies are recorded in this chart; absence of a record does not establish that he has none.", source_ids=["empty:allergies"])])
    response, _ = answer_followup(chart202, "Does he have any documented allergies?", [], ScriptedLLM([lookup, final]), settings, "cid-empty", today)
    assert response.state == ResponseState.COMPLETE and len(response.claims) == 1
    assert response.citations[0].type == "empty" and "no allergies records" in response.citations[0].label


def test_derived_records_carry_source_ids(chart101, today):
    ctx = ChartContext(chart101, today)
    rules = json.loads(tool(ctx, "run_constraint_checks").invoke({"pid": 101}))
    assert {r["source_id"] for r in rules["records"]} >= {"rule:ALLERGY-1", "rule:LAB-1"}
    signals = json.loads(tool(ctx, "get_compliance_signals").invoke({"pid": 101}))
    assert signals["records"][0]["source_id"] == "signal:1" and signals["records"][0]["based_on"]


def test_a_lab_read_from_a_document_says_which_document_and_page(chart101, today):
    """An answer about what changed has to be able to tell a machine-read value from one a human
    entered, and point at the page it came from."""
    from copilot.schemas import Lab

    chart = chart101.model_copy(deep=True)
    chart.labs.append(Lab(source_id="lab:7777", test="Potassium", value="5.4", units="mmol/L",
                          date=str(today), document_id=412, page=2))
    ctx = ChartContext(chart, today)
    rows = json.loads(tool(ctx, "get_labs").invoke({"pid": chart.patient.pid, "test": "potassium"}))["records"]

    read = [r for r in rows if r["source_id"] == "lab:7777"][0]
    assert read["read_from_document"] == "doc:412" and read["document_page"] == 2
    assert all(r["read_from_document"] is None for r in rows if r["source_id"] != "lab:7777")
