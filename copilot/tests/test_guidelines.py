"""Guideline retrieval, offline (BM25 only), and evidence under the verifier's rules."""

import dataclasses

from langchain_core.messages import AIMessage

from copilot.agent import answer_followup
from copilot.guidelines.retrieve import GuidelineIndex, conditions_from_problems, index_entries, load_corpus
from copilot.llm import ScriptedLLM
from copilot.schemas import AnswerDraft, Claim, ResponseState


def tool_call(name, args, call_id="c1"):
    return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": call_id, "type": "tool_call"}])


# --- the corpus ------------------------------------------------------------------------

def test_corpus_is_small_sectioned_and_citable():
    chunks = load_corpus()
    assert 15 <= len(chunks) <= 25
    ids = [c.source_id for c in chunks]
    assert len(set(ids)) == len(ids) and all(i.startswith("guideline:") and "#" in i for i in ids)
    assert all(c.url.startswith("https://") and c.publisher for c in chunks)
    assert "guideline:medlineplus-hyperkalemia#causes" in ids and "guideline:uspstf-htn-2021#recommendation" in ids


def test_a_chunk_record_carries_the_citation_v2_fields():
    chunk = next(c for c in load_corpus() if c.source_id == "guideline:uspstf-htn-2021#recommendation")
    record = chunk.record()
    assert record["kind"] == "guideline" and record["page_or_section"] == "Recommendation"
    assert record["field_or_chunk_id"] == chunk.source_id and "18 years or older" in record["quote_or_value"]


# --- search, offline -------------------------------------------------------------------

def test_offline_search_finds_the_hyperkalemia_causes_chunk(settings):
    index = GuidelineIndex(dataclasses.replace(settings, embed_model="none", rerank="none"))
    assert index.offline
    hits = index.search("high potassium ACE inhibitor causes", top_k=3)
    assert hits and hits[0].chunk.source_id == "guideline:medlineplus-hyperkalemia#causes"
    assert hits[0].bm25_rank == 1 and hits[0].dense_rank is None and hits[0].rerank_score is None


def test_condition_match_is_a_boost_not_a_filter(settings):
    index = GuidelineIndex(dataclasses.replace(settings, embed_model="none", rerank="none"))
    plain = index.search("screening recommendation adults", top_k=10)
    boosted = index.search("screening recommendation adults", conditions={"diabetes"}, top_k=5)
    # A boost reorders relevant chunks; it never introduces one that did not match the query.
    assert {h.chunk.source_id for h in boosted} <= {h.chunk.source_id for h in plain}
    assert any(h.condition_match for h in boosted) and not any(h.condition_match for h in plain)
    assert boosted[0].condition_match, "with the boost, a chunk about the chart's condition ranks first"


def test_nothing_matches_returns_nothing(settings):
    index = GuidelineIndex(dataclasses.replace(settings, embed_model="none", rerank="none"))
    assert index.search("topiramate migraine prophylaxis dosing") == []


def test_conditions_are_derived_from_problem_titles():
    assert conditions_from_problems(["Essential hypertension", "Type 2 diabetes mellitus"]) == {"hypertension", "diabetes"}
    assert conditions_from_problems(["Acute bronchitis"]) == set()


# --- evidence in an answer ------------------------------------------------------------

HYPERK = "guideline:medlineplus-hyperkalemia#causes"


def test_evidence_is_kept_apart_and_cited_to_the_guideline(chart101, settings, today):
    final = AnswerDraft(
        claims=[Claim(text="Potassium was 5.4 mmol/L on 2026-08-16.", source_ids=["lab:6001"])],
        evidence=[Claim(text="ACE inhibitors are named among the causes of a high potassium level.", source_ids=[HYPERK])],
    )
    llm = ScriptedLLM([tool_call("get_labs", {"pid": 101, "test": "potassium"}),
                       tool_call("search_guidelines", {"query": "high potassium ACE inhibitor"}, "c2"), final])
    response, _ = answer_followup(chart101, "What does guidance say about high potassium with an ACE inhibitor?", [], llm, settings, "cid-g1", today)
    assert response.state == ResponseState.COMPLETE
    assert [c.source_ids for c in response.claims] == [["lab:6001"]]
    assert [c.source_ids for c in response.evidence] == [[HYPERK]]
    guideline_citations = [c for c in response.citations if c.source_type == "guideline"]
    assert guideline_citations and guideline_citations[0].page_or_section == "Causes"
    assert "search_guidelines" in response.tool_calls


def test_a_patient_claim_may_not_cite_a_guideline_alone(chart101, settings, today):
    final = AnswerDraft(claims=[Claim(text="Her potassium is a high potassium level.", source_ids=["guideline:medlineplus-hyperkalemia#definition"])])
    llm = ScriptedLLM([tool_call("search_guidelines", {"query": "hyperkalemia definition"}), final])
    response, _ = answer_followup(chart101, "Is her potassium high per guidance?", [], llm, settings, "cid-g2", today)
    assert response.claims == [] and response.removed_claims and "guideline evidence only" in response.removed_claims[0].reason


def test_evidence_without_a_guideline_citation_is_removed(chart101, settings, today):
    final = AnswerDraft(claims=[], evidence=[Claim(text="Screening is recommended for adults.", source_ids=["problem:9001"])])
    llm = ScriptedLLM([tool_call("get_problems", {"pid": 101}), final])
    response, _ = answer_followup(chart101, "What does guidance say about screening?", [], llm, settings, "cid-g3", today)
    assert response.evidence == [] and any("cites no guideline" in r.reason for r in response.removed_claims)


def test_evidence_numbers_must_be_in_the_cited_chunk(chart101, settings, today):
    a1c = "guideline:medlineplus-a1c#result-ranges"
    final = AnswerDraft(claims=[], evidence=[Claim(text="Diabetes is an A1C of 7.0% or higher.", source_ids=[a1c]),
                                             Claim(text="Diabetes is an A1C of 6.5% or higher.", source_ids=[a1c])])
    llm = ScriptedLLM([tool_call("search_guidelines", {"query": "A1C ranges diabetes"}), final])
    response, _ = answer_followup(chart101, "What A1c means diabetes?", [], llm, settings, "cid-g4", today)
    assert [c.text for c in response.evidence] == ["Diabetes is an A1C of 6.5% or higher."]
    assert any("7.0" in r.reason for r in response.removed_claims)


def test_retrieved_chunks_are_citable_only_in_the_turn_they_were_retrieved(chart101, settings, today):
    final = AnswerDraft(claims=[], evidence=[Claim(text="ACE inhibitors are named among the causes of a high potassium level.", source_ids=[HYPERK])])
    llm = ScriptedLLM([tool_call("get_labs", {"pid": 101}), final])   # no search this turn
    response, _ = answer_followup(chart101, "And the guidance again?", [], llm, settings, "cid-g5", today)
    assert response.evidence == [] and response.removed_claims


def test_index_entries_are_keyed_by_citable_id(settings):
    index = GuidelineIndex(dataclasses.replace(settings, embed_model="none", rerank="none"))
    entries = index_entries(index.search("hypertension screening office blood pressure", top_k=2))
    assert all(k.startswith("guideline:") and v["kind"] == "guideline" for k, v in entries.items())
