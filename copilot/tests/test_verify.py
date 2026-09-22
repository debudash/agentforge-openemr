from copilot.agent import verification_index
from copilot.schemas import BriefDraft, BriefSection, Claim
from copilot.tools import ChartContext
from copilot.verify import check_claim, citations_for, verify_brief, verify_claims


def index_for(chart, today):
    return verification_index(chart, ChartContext(chart, today))


def test_claim_without_source_is_removed(chart101, today):
    reason = check_claim(Claim(text="Potassium was 5.4 mmol/L.", source_ids=[]), index_for(chart101, today), set())
    assert reason == "no source cited"


def test_claim_citing_another_patients_record_is_removed(chart101, chart202, today):
    idx = index_for(chart101, today)
    reason = check_claim(Claim(text="Hemoglobin 15.0 g/dL.", source_ids=["lab:6101"]), idx, set())
    assert "not in this patient's chart" in reason


def test_numbers_must_appear_in_cited_records(chart101, today):
    idx = index_for(chart101, today)
    assert check_claim(Claim(text="Potassium 5.4 mmol/L on 2026-08-16.", source_ids=["lab:6001"]), idx, set()) is None
    assert check_claim(Claim(text="Potassium 5.4 mmol/L on 16 August 2026.", source_ids=["lab:6001"]), idx, set()) is None
    reason = check_claim(Claim(text="Potassium 5.9 mmol/L.", source_ids=["lab:6001"]), idx, set())
    assert "5.9" in reason


def test_demo_reference_numbers_verify_when_lab_is_cited(chart101, today):
    idx = index_for(chart101, today)
    claim = Claim(text="Potassium 5.4 mmol/L is above the demo reference range of 3.5-5 mmol/L.", source_ids=["lab:6001"])
    assert check_claim(claim, idx, set()) is None


def test_recommendations_are_removed(chart101, today):
    idx = index_for(chart101, today)
    reason = check_claim(Claim(text="You should start amlodipine.", source_ids=["problem:9001"]), idx, set())
    assert "recommendation" in reason


def test_derived_rule_and_signal_ids_are_citable(chart101, today):
    idx = index_for(chart101, today)
    assert "rule:ALLERGY-1" in idx and "signal:1" in idx
    kept, removed = verify_claims([Claim(text="Rule ALLERGY-1 flagged a penicillin conflict.", source_ids=["rule:ALLERGY-1"])], idx)
    assert kept and not removed


def test_small_counts_and_allowed_numbers_pass(chart101, today):
    idx = index_for(chart101, today)
    claim = Claim(text="There are 2 active disorders in the previous 24 hours window.", source_ids=["problem:9001", "problem:9002"])
    assert check_claim(claim, idx, {"24"}) is None


def test_verify_brief_reports_removed_per_section(chart101, today):
    draft = BriefDraft(sections=[BriefSection(key="medications", title="Medications", claims=[
        Claim(text="Lisinopril 10 MG is active.", source_ids=["prescription:7001"]),
        Claim(text="Metformin 500 MG is active.", source_ids=[]),
    ])])
    sections, removed = verify_brief(draft, index_for(chart101, today))
    assert len(sections[0].claims) == 1 and len(removed) == 1


def test_citations_have_type_label_date(chart101, today):
    cites = citations_for(["lab:6001", "prescription:7001", "nope:1"], index_for(chart101, today))
    assert [c.type for c in cites] == ["lab", "prescription"]
    assert cites[0].date == "2026-08-16" and "Potassium" in cites[0].label


# --- Week 2: documents and guideline evidence under the same rules ---------------

def index_with_documents(chart, today):
    idx = index_for(chart, today)
    idx["doc:412"] = {"kind": "document", "doc_type": "lab_pdf", "name": "metro-labs.pdf", "date": "2026-09-18",
                      "page_or_section": "p2", "field_or_chunk_id": "results[0].value", "quote_or_value": "Potassium 5.4 mmol/L"}
    idx["guideline:uspstf-htn-2021"] = {"kind": "guideline", "title": "USPSTF hypertension screening", "section": "3.2",
                                        "text": "Screen adults 18 years or older for hypertension."}
    return idx


def test_a_patient_claim_may_not_cite_guideline_evidence_alone(chart101, today):
    idx = index_with_documents(chart101, today)
    claim = Claim(text="Adults should be screened for hypertension.", source_ids=["guideline:uspstf-htn-2021"])
    reason = check_claim(claim, idx, set())
    assert reason.startswith("cites guideline evidence only")
    from copilot.verify import removal_reason_code
    assert removal_reason_code(reason) == "guideline_only"


def test_guideline_only_is_allowed_in_the_evidence_section(chart101, today):
    idx = index_with_documents(chart101, today)
    claim = Claim(text="Adults should be screened for hypertension.", source_ids=["guideline:uspstf-htn-2021"])
    assert check_claim(claim, idx, set(), allow_guideline_only=True) is None
    kept, removed = verify_claims([claim], idx, allow_guideline_only=True)
    assert kept and not removed


def test_guideline_beside_a_patient_record_is_fine(chart101, today):
    idx = index_with_documents(chart101, today)
    claim = Claim(text="Hypertension is on the problem list; screening is recommended for adults.",
                  source_ids=["problem:9001", "guideline:uspstf-htn-2021"])
    # "recommended" here is the guideline's wording, and the boundary regex targets advice phrasings;
    # the point of this test is the citation mix, so keep the sentence clear of those.
    claim = Claim(text="Hypertension is on the problem list; the guideline covers adults 18 years or older.",
                  source_ids=["problem:9001", "guideline:uspstf-htn-2021"])
    assert check_claim(claim, idx, {"18"}) is None


def test_a_number_read_from_a_document_must_match_the_persisted_record(chart101, today):
    """Rule 3 for documents: the document index entry carries no values, the lab row does."""
    idx = index_with_documents(chart101, today)
    only_doc = Claim(text="Potassium was 5.9 mmol/L on the lab report.", source_ids=["doc:412"])
    assert "5.9" in check_claim(only_doc, idx, set())
    with_row = Claim(text="Potassium was 5.4 mmol/L on the lab report.", source_ids=["doc:412", "lab:6001"])
    assert check_claim(with_row, idx, set()) is None


def test_citations_for_documents_and_guidelines_carry_v2_fields(chart101, today):
    idx = index_with_documents(chart101, today)
    cites = {c.source_id: c for c in citations_for(["lab:6001", "doc:412", "guideline:uspstf-htn-2021"], idx)}
    assert cites["lab:6001"].source_type == "record" and cites["lab:6001"].page_or_section is None
    doc = cites["doc:412"]
    assert doc.source_type == "document" and doc.page_or_section == "p2" and doc.quote_or_value == "Potassium 5.4 mmol/L"
    assert doc.label == "lab_pdf metro-labs.pdf"
    guide = cites["guideline:uspstf-htn-2021"]
    assert guide.source_type == "guideline" and guide.label == "USPSTF hypertension screening 3.2"
