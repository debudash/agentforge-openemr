"""The agent loop with a scripted model: loop cap, scope denials, verification, failure states."""

from langchain_core.messages import AIMessage

from copilot.agent import answer_followup, generate_brief
from copilot.llm import ScriptedLLM
from copilot.schemas import AnswerDraft, BriefDraft, BriefSection, Claim, ResponseState


def tool_call(name, args, call_id="c1"):
    return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": call_id, "type": "tool_call"}])


def test_followup_loop_stops_at_five_iterations_and_reports_partial(chart101, settings, today):
    rounds = [tool_call("get_problems", {"pid": 101}, f"c{i}") for i in range(8)]   # model never stops calling tools
    final = AnswerDraft(claims=[Claim(text="Essential hypertension is on the active problem list.", source_ids=["problem:9001"])])
    llm = ScriptedLLM(rounds + [final])
    response, turn = answer_followup(chart101, "What problems does she have?", [], llm, settings, "cid-1", today)
    assert response.iterations == 5
    assert response.state == ResponseState.PARTIAL and "tool-call limit" in response.state_reason
    assert response.claims and response.tool_calls == ["get_problems"] * 5
    assert len(turn) == 2


def test_followup_answer_verified_and_cross_patient_citation_removed(chart101, settings, today):
    final = AnswerDraft(claims=[
        Claim(text="Potassium 5.4 mmol/L on 2026-08-16 is above the demo reference range.", source_ids=["lab:6001"]),
        Claim(text="Hemoglobin 15.0 g/dL.", source_ids=["lab:6101"]),   # belongs to pid 202
    ])
    llm = ScriptedLLM([tool_call("get_labs", {"pid": 101, "test": "potassium"}), final])
    response, _ = answer_followup(chart101, "Latest potassium?", [], llm, settings, "cid-2", today)
    assert [c.source_ids for c in response.claims] == [["lab:6001"]]
    assert response.removed_claims and "not in this patient's chart" in response.removed_claims[0].reason
    assert response.state == ResponseState.PARTIAL
    assert response.citations[0].type == "lab"


def test_followup_model_asking_for_other_patient_is_denied_by_tool(chart101, settings, today):
    final = AnswerDraft(claims=[], missing="Only the active patient can be read; the other patient was not retrieved.")
    llm = ScriptedLLM([tool_call("get_medications", {"pid": 202}), final])
    response, _ = answer_followup(chart101, "What is patient 202 taking?", [], llm, settings, "cid-3", today)
    assert response.claims == [] and response.state == ResponseState.COMPLETE
    assert response.missing and response.tool_calls == ["get_medications"]


def test_followup_boundary_answer_is_complete_without_claims(chart101, settings, today):
    final = AnswerDraft(claims=[], boundary="I cannot recommend treatment; I can retrieve the documented blood pressure history.")
    response, _ = answer_followup(chart101, "Should I start amlodipine?", [], llm := ScriptedLLM([final]), settings, "cid-4", today)
    assert response.boundary and response.state == ResponseState.COMPLETE


def test_followup_retries_a_malformed_tool_round_once(chart101, settings, today):
    """First tool round raises (unparsable tool call), the retry succeeds, the answer completes."""
    final = AnswerDraft(claims=[Claim(text="Essential hypertension is on the active problem list.", source_ids=["problem:9001"])])

    class Flaky(ScriptedLLM):
        def __init__(self):
            super().__init__([tool_call("get_problems", {"pid": 101}), final])
            self.failed_once = False

        def invoke_with_tools(self, messages, tools):
            if not self.failed_once:
                self.failed_once = True
                raise ValueError("Function get_problems arguments are not valid JSON")
            return super().invoke_with_tools(messages, tools)

    llm = Flaky()
    response, _ = answer_followup(chart101, "What problems does she have?", [], llm, settings, "cid-retry", today)
    assert response.state == ResponseState.COMPLETE and response.tool_calls == ["get_problems"]
    assert response.iterations == 2   # the failed round and its retry count as one iteration; the final round is the second


def test_followup_model_failure_is_unable_to_answer(chart101, settings, today):
    class Broken:
        def invoke_with_tools(self, *_):
            raise ConnectionError("down")

        def structured(self, *_):
            raise ConnectionError("down")

    response, _ = answer_followup(chart101, "Anything?", [], Broken(), settings, "cid-5", today)
    assert response.state == ResponseState.UNABLE and "unavailable" in response.state_reason


def test_brief_complete_when_all_claims_verify(chart101, settings, today):
    draft = BriefDraft(sections=[
        BriefSection(key="primary_diagnosis", title="Primary diagnosis", claims=[
            Claim(text="Essential hypertension, documented since 2012-05-10, matches the most recent encounter reason.", source_ids=["problem:9001", "encounter:3001"])]),
        BriefSection(key="allergies", title="Allergies", claims=[Claim(text="Penicillin V allergy with rash recorded.", source_ids=["allergy:8001"])]),
    ])
    response = generate_brief(chart101, ScriptedLLM([draft]), settings, "cid-6", today)
    assert response.state == ResponseState.COMPLETE
    assert response.rule_outcomes and any(o.outcome == "flag" for o in response.rule_outcomes)
    assert response.comparison_window.startswith("previous 24 hours")


def test_brief_partial_when_a_source_failed(chart303, settings, today):
    draft = BriefDraft(sections=[BriefSection(key="medications", title="Medications", claims=[
        Claim(text="Clopidogrel 75 MG is active.", source_ids=["prescription:7301"])])])
    response = generate_brief(chart303, ScriptedLLM([draft]), settings, "cid-7", today)
    assert response.state == ResponseState.PARTIAL and "labs" in response.state_reason


def test_brief_unable_when_model_output_invalid_twice(chart101, settings, today):
    response = generate_brief(chart101, ScriptedLLM([]), settings, "cid-8", today)
    assert response.state == ResponseState.UNABLE and response.sections == []
