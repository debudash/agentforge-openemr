"""The agent loop with a scripted model: loop cap, scope denials, verification, failure states."""

from langchain_core.messages import AIMessage

from copilot.agent import answer_followup, generate_brief
from copilot.config import Settings
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

        def invoke_with_tools(self, messages, tools, require_tool=False):
            if not self.failed_once:
                self.failed_once = True
                raise ValueError("Function get_problems arguments are not valid JSON")
            return super().invoke_with_tools(messages, tools, require_tool)

    llm = Flaky()
    response, _ = answer_followup(chart101, "What problems does she have?", [], llm, settings, "cid-retry", today)
    assert response.state == ResponseState.COMPLETE and response.tool_calls == ["get_problems"]
    assert response.iterations == 2   # the failed round and its retry count as one iteration; the final round is the second


def test_an_off_topic_question_is_refused_when_the_turn_also_finds_nothing(chart101, today):
    """The transcript case: allergies in memory, then 'what is the weather'. The pre-check says
    off-topic and the turn looks nothing up, so the scope sentence stands.

    The pre-check alone no longer decides. It reads four words with no chart and no history, and
    on terse clinical questions it is a coin flip -- so it is advice, and what settles the turn is
    whether anything was found. Here nothing is, and the two agree."""
    from dataclasses import replace
    from langchain_core.messages import AIMessage, HumanMessage
    from copilot.agent import SCOPE_STATEMENT
    from copilot.schemas import AnswerDraft, TopicCheck
    settings = replace(Settings(), topic_check=True)
    history = [HumanMessage(content="what are the allergies"), AIMessage(content="Mold (organism) with reaction 1, begun 1993-08-18.")]
    llm = ScriptedLLM([TopicCheck(about_patient_record=False),
                       AnswerDraft(claims=[], off_topic=True, missing="That is a general knowledge question.")])
    response, turn = answer_followup(chart101, "what is the weather", history, llm, settings, "cid-topic-no", today)
    assert response.off_topic and response.state == ResponseState.COMPLETE
    assert response.claims == [] and response.tool_calls == []
    assert response.missing == SCOPE_STATEMENT


def test_a_terse_chart_question_the_pre_check_gets_wrong_is_still_answered(chart101, today):
    """The bug this inverts: "what changed" was refused eight times in nine because a small model
    was asked to classify two words. Finding a record overrides the opinion."""
    from dataclasses import replace
    from langchain_core.messages import AIMessage
    from copilot.agent import SCOPE_STATEMENT
    from copilot.schemas import AnswerDraft, Claim, TopicCheck
    settings = replace(Settings(), topic_check=True)
    lookup = AIMessage(content="", tool_calls=[{"name": "get_labs", "args": {"pid": 101}, "id": "c1", "type": "tool_call"}])
    answer = AnswerDraft(claims=[Claim(text="Potassium was 5.4 mmol/L on 2026-08-16.", source_ids=["lab:6001"])])
    llm = ScriptedLLM([TopicCheck(about_patient_record=False), lookup, answer])
    response, turn = answer_followup(chart101, "what changed", [], llm, settings, "cid-terse", today)
    assert not response.off_topic, "a question that found a record cannot be off-topic"
    assert response.claims and response.tool_calls == ["get_labs"]
    assert response.missing != SCOPE_STATEMENT if response.missing else True


def test_topic_check_yes_proceeds_normally(chart101, today):
    from dataclasses import replace
    from copilot.schemas import TopicCheck
    settings = replace(Settings(), topic_check=True)
    final = AnswerDraft(claims=[Claim(text="Potassium was 5.4 mmol/L on 2026-08-16.", source_ids=["lab:6001"])])
    llm = ScriptedLLM([TopicCheck(about_patient_record=True), tool_call("get_labs", {"pid": 101, "test": "potassium"}), final])
    response, _ = answer_followup(chart101, "her potassium again?", [], llm, settings, "cid-topic-yes", today)
    assert response.state == ResponseState.COMPLETE and response.tool_calls == ["get_labs"]


def test_topic_check_error_fails_open(chart101, today):
    from dataclasses import replace
    settings = replace(Settings(), topic_check=True)
    final = AnswerDraft(claims=[], boundary="I cannot recommend treatment.")
    llm = ScriptedLLM([final])   # no TopicCheck scripted: the pre-check raises and is ignored
    response, _ = answer_followup(chart101, "should I start amlodipine?", [], llm, settings, "cid-topic-err", today)
    assert response.boundary and response.state == ResponseState.COMPLETE


def test_followup_off_topic_question_is_named_as_such(chart101, settings, today):
    final = AnswerDraft(claims=[], off_topic=True, missing="This co-pilot only answers questions about the selected patient's chart.")
    second = AnswerDraft(claims=[], off_topic=True, missing="This co-pilot only answers questions about the selected patient's chart.")
    response, turn = answer_followup(chart101, "What is the weather like today?", [], ScriptedLLM([final, second]), settings, "cid-weather", today)
    assert response.state == ResponseState.COMPLETE and response.off_topic
    assert response.state_reason == "not a question about this patient's record"
    assert response.claims == [] and response.tool_calls == []
    assert "selected patient" in turn[1].content


def test_followup_off_topic_flag_with_poor_wording_gets_the_scope_statement(chart101, settings, today):
    """The model flags off-topic but explains it in lab terms (seen live): the fixed sentence replaces it."""
    from copilot.agent import SCOPE_STATEMENT
    final = AnswerDraft(claims=[], off_topic=True, missing="No tool results were obtained in this turn to support any claims about the patient's chart.")
    second = AnswerDraft(claims=[], off_topic=True, missing="Nothing in the chart to cite.")
    response, _ = answer_followup(chart101, "whats the weather", [], ScriptedLLM([final, second]), settings, "cid-poor", today)
    assert response.off_topic and response.missing == SCOPE_STATEMENT


def test_followup_no_lookup_is_treated_as_off_topic_whatever_the_model_wrote(chart101, settings, today):
    """The screenshot case: 'whats the weather', no flag, no tools, no claims, and a model-written
    'missing' about lab results. The agent imposes the scope statement and the off-topic reason."""
    from copilot.agent import SCOPE_STATEMENT
    final = AnswerDraft(claims=[], missing="No tool results were obtained in this turn to support any claims about lab results.")
    # Two empty passes: the agent tells a model that looked nothing up to go and look, and only
    # calls the question off-topic when the second pass comes back empty too.
    second = AnswerDraft(claims=[], missing="Still nothing to cite.")
    response, _ = answer_followup(chart101, "whats the weather", [], ScriptedLLM([final, second]), settings, "cid-nolookup", today)
    assert response.off_topic and response.state == ResponseState.COMPLETE
    assert response.state_reason == "not a question about this patient's record"
    assert response.missing == SCOPE_STATEMENT and response.tool_calls == []


def test_followup_no_lookup_keeps_the_models_own_scope_statement(chart101, settings, today):
    final = AnswerDraft(claims=[], missing="Only the active patient (id 101) can be read; patient 202 was not retrieved.")
    second = AnswerDraft(claims=[], missing="Only the active patient (id 101) can be read; patient 202 was not retrieved.")
    response, _ = answer_followup(chart101, "and patient 202?", [], ScriptedLLM([final, second]), settings, "cid-scope", today)
    assert response.off_topic and "active patient" in response.missing


def test_followup_off_topic_flag_wins_over_stray_claims(chart101, settings, today):
    """A model that flags off-topic but also copies chart facts: the facts are discarded, the flag stands.

    Both opinions are scripted, because one no longer decides: the pre-check says off-topic and
    the model says off-topic, so the stray facts it copied in anyway are what gets thrown away."""
    from copilot.schemas import TopicCheck
    final = AnswerDraft(claims=[Claim(text="Essential hypertension is on the problem list.", source_ids=["problem:9001"])], off_topic=True)
    llm = ScriptedLLM([TopicCheck(about_patient_record=False), final])
    response, _ = answer_followup(chart101, "what is the weather", [], llm, settings, "cid-mixed", today)
    assert response.state == ResponseState.COMPLETE and response.off_topic and response.claims == []
    assert response.removed_claims[0].reason.startswith("off-topic question")
    assert "selected patient" in (response.missing or "")


def test_followup_cannot_restate_memory_without_a_fresh_lookup(chart101, settings, today):
    """Your sequence: a lab answer in memory, then an unrelated question the model answers by re-emitting
    the lab claims with no tool call. Those ids were not returned this turn, so every claim is removed."""
    from langchain_core.messages import AIMessage, HumanMessage
    history = [HumanMessage(content="What were her latest labs?"),
               AIMessage(content="Potassium was 5.4 mmol/L on 2026-08-16. Sodium was 138 mmol/L on 2026-08-16.")]
    regurgitated = AnswerDraft(claims=[Claim(text="Potassium was 5.4 mmol/L on 2026-08-16.", source_ids=["lab:6001"]),
                                       Claim(text="Sodium was 138 mmol/L on 2026-08-16.", source_ids=["lab:6002"])])
    # The model is told to look the facts up and answers from memory a second time: still nothing.
    llm = ScriptedLLM([regurgitated, regurgitated])
    response, _ = answer_followup(chart101, "what is the weather", history, llm, settings, "cid-memory", today)
    assert response.claims == [] and response.tool_calls == []
    assert len(response.removed_claims) == 2 and "restated without a lookup" in response.removed_claims[0].reason
    assert response.state == ResponseState.UNABLE and "no tool was called" in response.state_reason
    assert response.iterations == 2   # the first pass and the re-lookup pass, no tools in either


def test_followup_relookup_recovers_a_memory_answer(chart101, settings, today):
    """'Her potassium again?' answered from memory with a made-up id, then, when told to look it up,
    fetched properly: the second pass produces a verified answer."""
    from langchain_core.messages import AIMessage, HumanMessage
    history = [HumanMessage(content="What were her latest labs?"), AIMessage(content="Potassium was 5.4 mmol/L on 2026-08-16.")]
    from_memory = AnswerDraft(claims=[Claim(text="Potassium was 5.4 mmol/L on 2026-08-16.", source_ids=["lab:919"])])
    fetched = AnswerDraft(claims=[Claim(text="Potassium was 5.4 mmol/L on 2026-08-16.", source_ids=["lab:6001"])])
    llm = ScriptedLLM([from_memory, tool_call("get_labs", {"pid": 101, "test": "potassium"}), fetched])
    response, _ = answer_followup(chart101, "OK, and her potassium again?", history, llm, settings, "cid-relookup", today)
    assert response.state == ResponseState.COMPLETE and len(response.claims) == 1
    assert response.tool_calls == ["get_labs"] and response.iterations == 3
    assert response.removed_claims == []   # only the final pass is reported
    assert "tools-required" in llm.calls   # the re-lookup pass forced the tool call


def test_followup_fresh_lookup_still_verifies(chart101, settings, today):
    """The same claim IS accepted when the turn's own tool call returned the record."""
    final = AnswerDraft(claims=[Claim(text="Potassium was 5.4 mmol/L on 2026-08-16.", source_ids=["lab:6001"])])
    llm = ScriptedLLM([tool_call("get_labs", {"pid": 101, "test": "potassium"}), final])
    response, _ = answer_followup(chart101, "latest potassium?", [], llm, settings, "cid-fresh", today)
    assert response.state == ResponseState.COMPLETE and len(response.claims) == 1


def test_followup_unknown_tool_name_is_reported_and_recoverable(chart101, settings, today):
    """The model invents a tool name, is told which tools exist, then calls a real one."""
    final = AnswerDraft(claims=[Claim(text="Penicillin V allergy with rash recorded.", source_ids=["allergy:8001"])])
    llm = ScriptedLLM([tool_call("get_allergy_conflicts", {"pid": 101}), tool_call("get_allergies", {"pid": 101}, "c2"), final])
    response, _ = answer_followup(chart101, "Any allergy conflicts?", [], llm, settings, "cid-unknown", today)
    assert response.tool_calls == ["unknown:get_allergy_conflicts", "get_allergies"]
    assert response.state == ResponseState.COMPLETE and len(response.claims) == 1


def test_followup_malformed_tool_arguments_become_an_error_result(chart101, settings, today):
    """A corrupted pid ('10>\\n101', as seen from the free model) must not crash the turn: the tool
    answers with an error and the model corrects the call in its next round."""
    final = AnswerDraft(claims=[Claim(text="Lisinopril 10 MG Oral Tablet is active.", source_ids=["prescription:7001"])])
    llm = ScriptedLLM([tool_call("get_medications", {"pid": "10>\n101"}), tool_call("get_medications", {"pid": 101}, "c2"), final])
    response, _ = answer_followup(chart101, "What is she taking?", [], llm, settings, "cid-badargs", today)
    assert response.tool_calls == ["invalid-args:get_medications", "get_medications"]
    assert response.state == ResponseState.COMPLETE and len(response.claims) == 1


def test_followup_model_failure_is_unable_to_answer(chart101, settings, today):
    class Broken:
        def invoke_with_tools(self, *_, **__):
            raise ConnectionError("down")

        def structured(self, *_, **__):
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
