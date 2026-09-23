"""The supervisor graph with scripted models: routing, the persist interrupt, and what-changed claims."""

import base64
from pathlib import Path

from copilot.documents.schemas import DocumentCitation, ExtractedField, LabDocument, LabResult
from copilot.llm import ScriptedLLM
from copilot.schemas import BriefDraft, BriefSection, Claim
from copilot.supervisor import Supervisor

FIXTURE = Path(__file__).resolve().parent.parent / "evals" / "stage2" / "fixtures" / "documents" / "metro-labs-jane-doe.pdf"
DOC = 412


def field(value, quote=None, page=1, name="value"):
    return ExtractedField(value=value, confidence=0.9, citation=DocumentCitation(source_id=f"doc:{DOC}", page=page, field=name, quote=quote or value))


def proposal():
    def res(test, value, unit, rng, flag, page):
        return LabResult(test_name=field(test, test, page, "test_name"), value=field(value, value, page), unit=field(unit, unit, page, "unit"),
                         reference_range=field(rng, rng, page, "reference_range"), collection_date=field("2026-09-17", "Collected: 2026-09-17", 1, "collection_date"),
                         abnormal_flag=field(flag, flag, page, "abnormal_flag") if flag else ExtractedField.absent())
    return LabDocument(source_id=f"doc:{DOC}", page_count=2, patient_ref=field("Jane Doe", "Patient: Jane Doe", 1, "patient_ref"),
                       report_date=field("2026-09-18", "Reported: 2026-09-18", 1, "report_date"),
                       performing_lab=field("Metro Clinical Labs", "METRO CLINICAL LABS", 1, "performing_lab"), ordering_provider=ExtractedField.absent(),
                       results=[res("Potassium", "5.4", "mmol/L", "3.5-5.0", "H", 1), res("Sodium", "140", "mmol/L", "135-145", "", 1)])


def brief_draft():
    return BriefDraft(sections=[BriefSection(key="primary_diagnosis", title="Primary diagnosis",
                                             claims=[Claim(text="Essential hypertension is on the active problem list.", source_ids=["problem:9001"])])])


def supervisor(chart, settings, vision_responses=None):
    return Supervisor(settings, lambda: ScriptedLLM([brief_draft()]), lambda: ScriptedLLM(vision_responses if vision_responses is not None else [proposal()]),
                      lambda sid, pid: chart)


def manifest(processed=False, content=True):
    doc = {"doc_id": DOC, "doc_type": "lab_pdf", "name": "metro-labs.pdf", "date": "2026-09-18", "processed": processed}
    if content and not processed:
        doc["content_base64"] = base64.b64encode(FIXTURE.read_bytes()).decode("ascii")
    return [doc]


def edges(result):
    return [(h["from"], h["to"]) for h in result["handoffs"]]


def test_no_documents_goes_straight_to_the_brief(chart101, settings):
    out = supervisor(chart101, settings).start("sid-1", 101, [], "cid-s1")
    assert out["phase"] == "done" and out["brief"]["state"] == "complete" and out["changes"] == []
    assert edges(out) == [("supervisor", "evidence_retriever"), ("evidence_retriever", "supervisor"), ("supervisor", "clinician")]
    assert all(h["reason"] for h in out["handoffs"])


def test_an_unread_document_is_extracted_then_control_returns_to_the_module(chart101, settings):
    sup = supervisor(chart101, settings)
    out = sup.start("sid-2", 101, manifest(), "cid-s2")
    assert out["phase"] == "extracted"
    assert len(out["extractions"]) == 1 and out["extractions"][0]["ok"] and len(out["extractions"][0]["result"]["document"]["results"]) == 2
    assert edges(out) == [("supervisor", "intake_extractor"), ("intake_extractor", "supervisor"), ("supervisor", "module")]
    assert "brief" not in out, "no brief before the module has persisted and re-read the chart"

    final = sup.resume("sid-2", 101, [{"doc_id": DOC, "doc_type": "lab_pdf", "source_ids": ["lab:9001", "lab:9002"], "order_id": 77, "skipped": []}], "cid-s2")
    assert final["phase"] == "done" and final["brief"]["state"] == "complete"
    assert edges(final)[3:] == [("module", "supervisor"), ("supervisor", "evidence_retriever"), ("evidence_retriever", "supervisor"), ("supervisor", "clinician")]
    assert len(final["changes"]) == 1
    change = final["changes"][0]
    assert change["source_ids"] == [f"doc:{DOC}"] and "2 result(s) added" in change["text"] and "pending clinician review" in change["text"]
    assert final["citations"][0]["source_type"] == "document" and final["removed"] == []


def test_a_document_the_module_refused_to_file_says_so_rather_than_nothing(chart101, settings):
    """The module reads the name on the report and will not file a document that names someone
    else. A refused document that produced no rows looks exactly like one that was never there,
    so the brief has to say which it was."""
    sup = supervisor(chart101, settings)
    sup.start("sid-9", 101, manifest(), "cid-s9")
    final = sup.resume("sid-9", 101, [{"doc_id": DOC, "doc_type": "lab_pdf", "source_ids": [], "skipped": [],
                                       "refused": "the document names a different patient"}], "cid-s9")
    assert final["phase"] == "done" and final["brief"]["state"] == "complete"
    change = final["changes"][0]
    assert "not filed" in change["text"] and "names a different patient" in change["text"]
    assert "remains stored for manual review" in change["text"]
    assert change["source_ids"] == [f"doc:{DOC}"] and final["removed"] == []


def test_a_document_that_cannot_be_read_is_reported_and_the_brief_still_happens(chart101, settings):
    out = supervisor(chart101, settings, vision_responses=[]).start("sid-3", 101, manifest(), "cid-s3")
    assert out["phase"] == "done", "nothing to persist, so no interrupt"
    assert out["failed"] and not out["extractions"]
    assert out["brief"]["state"] == "complete"
    assert len(out["changes"]) == 1 and "could not be read" in out["changes"][0]["text"]
    assert ("supervisor", "module") not in edges(out)


def test_an_already_read_document_is_not_read_again(chart101, settings):
    out = supervisor(chart101, settings).start("sid-4", 101, manifest(processed=True), "cid-s4")
    assert out["phase"] == "done" and out["changes"] == [] and ("supervisor", "intake_extractor") not in edges(out)


def test_the_vision_model_being_unapproved_fails_every_document_the_same_way(chart101, settings):
    def unapproved():
        raise RuntimeError("not on the allowlist")

    sup = Supervisor(settings, lambda: ScriptedLLM([brief_draft()]), unapproved, lambda sid, pid: chart101)
    out = sup.start("sid-5", 101, manifest(), "cid-s5")
    assert out["phase"] == "done" and out["failed"][0]["error"].startswith("vision model unavailable")
    assert "could not be read" in out["changes"][0]["text"]


def test_the_supervisor_itself_never_calls_a_model(chart101, settings):
    brief_llm = ScriptedLLM([brief_draft()])
    vision = ScriptedLLM([proposal()])
    sup = Supervisor(settings, lambda: brief_llm, lambda: vision, lambda sid, pid: chart101)
    sup.start("sid-6", 101, manifest(), "cid-s6")
    assert vision.calls == ["structured"] and brief_llm.calls == [], "only the extractor has called a model so far"
    sup.resume("sid-6", 101, [{"doc_id": DOC, "doc_type": "lab_pdf", "source_ids": ["lab:1"], "order_id": 1, "skipped": []}], "cid-s6")
    assert brief_llm.calls == ["structured"], "the retriever generated the brief; the supervisor added no calls"


def test_supervising_a_patient_makes_it_the_active_one_so_follow_ups_work(chart101, chart303, settings):
    """The patient tab opens, supervises, then asks. Week 1's tab selected on the way in; this path
    must too, or every follow-up from the patient record reads as access_denied."""
    import asyncio

    from copilot.llm import ScriptedLLM
    from copilot.schemas import AnswerDraft, ResponseState
    from copilot.session import SessionStore
    from langchain_core.messages import AIMessage

    lookup = AIMessage(content="", tool_calls=[{"name": "get_problems", "args": {"pid": 101}, "id": "c1", "type": "tool_call"}])
    answer = AnswerDraft(claims=[Claim(text="Essential hypertension is on the problem list.", source_ids=["problem:9001"])])
    store = SessionStore(settings, lambda: ScriptedLLM([brief_draft(), lookup, answer]))
    store.open("s" * 32, {"id": 8, "username": "doctor1", "name": "Dana Reyes", "groups": ["Physicians"]}, [chart101, chart303], "cid")
    store.sessions["s" * 32].patients[303].history.append("stale")

    out = asyncio.run(store.supervise("s" * 32, 101, [], lambda: ScriptedLLM([]), "cid-a"))

    assert out["phase"] == "done"
    assert store.sessions["s" * 32].active_pid == 101
    assert store.sessions["s" * 32].patients[303].history == []      # FR5 still holds
    assert asyncio.run(store.ask("s" * 32, 101, "how many hospitalizations?", "cid-b")).state == ResponseState.COMPLETE


def test_a_document_change_citation_opens_the_page_naming_the_patient(chart101, settings):
    """A "this was read" claim still has to open somewhere. Without a page and a quote the chip
    opened page 1 with nothing highlighted -- the overlay working, given nothing to point at."""
    sup = supervisor(chart101, settings)
    sup.start("sid-10", 101, manifest(), "cid-s10")
    final = sup.resume("sid-10", 101, [{"doc_id": DOC, "doc_type": "lab_pdf", "source_ids": ["lab:9001"],
                                        "order_id": 78, "skipped": []}], "cid-s10")
    citation = [c for c in final["citations"] if c["source_id"] == f"doc:{DOC}"][0]
    assert citation["source_type"] == "document"
    assert citation["page_or_section"] == "p1"
    assert citation["field_or_chunk_id"] == "patient_ref"
    assert "Jane Doe" in citation["quote_or_value"]


def test_a_document_that_could_not_be_read_offers_no_page_to_open(chart101, settings):
    """It still identifies itself -- a citation with nothing in it helps no one -- but it names
    the chart section rather than a page, because there is no page it managed to read."""
    out = supervisor(chart101, settings, vision_responses=[]).start("sid-11", 101, manifest(), "cid-s11")
    citation = [c for c in out["citations"] if c["source_id"] == f"doc:{DOC}"][0]
    assert citation["page_or_section"] == "documents", "no page was read, so none is offered"
    assert not str(citation["page_or_section"]).startswith("p1")
    assert citation["quote_or_value"] and "metro-labs" in citation["quote_or_value"]


def answer_draft(text="Potassium was 5.4 mmol/L on 2026-08-16.", sid="lab:6001"):
    from copilot.schemas import AnswerDraft
    return AnswerDraft(claims=[Claim(text=text, source_ids=[sid])])


def question_supervisor(chart, settings, answers, vision_responses=None):
    # The suite runs with the topic pre-check off (conftest), so the script is just the tool round
    # and the answer -- the same shape the other follow-up tests use.
    from langchain_core.messages import AIMessage
    lookup = AIMessage(content="", tool_calls=[{"name": "get_labs", "args": {"pid": 101}, "id": "c1", "type": "tool_call"}])
    scripted = [lookup, *answers]
    return Supervisor(settings, lambda: ScriptedLLM(scripted),
                      lambda: ScriptedLLM(vision_responses if vision_responses is not None else [proposal()]),
                      lambda sid, pid: chart)


def test_a_question_with_nothing_unread_goes_straight_to_the_retriever(chart101, settings):
    """Stage 3: the supervisor decides for a question exactly as it does for a brief."""
    out = question_supervisor(chart101, settings, [answer_draft()]).start(
        "sid-q1", 101, [], "cid-q1", question="what was the last potassium?")
    assert out["phase"] == "done" and out["brief"] is None
    assert out["answer"]["kind"] == "answer" and out["answer"]["claims"]
    assert edges(out) == [("supervisor", "evidence_retriever"), ("evidence_retriever", "supervisor"), ("supervisor", "clinician")]
    reasons = [h["reason"] for h in out["handoffs"]]
    assert any("question" in r for r in reasons), reasons


def test_a_question_asked_while_a_document_is_unread_reads_it_first(chart101, settings):
    """The reason a question belongs in the graph at all: asked a moment after an upload, it is
    answered from the chart that document produced, not from the chart as it was before."""
    sup = question_supervisor(chart101, settings, [answer_draft()])
    out = sup.start("sid-q2", 101, manifest(), "cid-q2", question="what changed?")
    assert out["phase"] == "extracted", "the supervisor routed to extraction before answering"
    assert edges(out) == [("supervisor", "intake_extractor"), ("intake_extractor", "supervisor"), ("supervisor", "module")]

    final = sup.resume("sid-q2", 101, [{"doc_id": DOC, "doc_type": "lab_pdf", "source_ids": ["lab:6001"],
                                        "order_id": 90, "skipped": []}], "cid-q2")
    assert final["phase"] == "done" and final["answer"]["claims"]
    assert ("supervisor", "evidence_retriever") in edges(final)
    assert all(h["reason"] for h in final["handoffs"]), "every handoff names its reason"


def test_a_question_turn_is_returned_for_memory(chart101, settings):
    out = question_supervisor(chart101, settings, [answer_draft()]).start(
        "sid-q3", 101, [], "cid-q3", question="what was the last potassium?")
    assert len(out["turn"]) == 2, "the question and the answer go back into conversation memory"
