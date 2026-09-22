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
