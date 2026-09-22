"""Document extraction with a scripted vision model: the checks that run after the model answers."""

from pathlib import Path

import pytest

from copilot.documents.extract import (
    ExtractionFailed,
    demote_uncited,
    extract_lab_document,
    page_count,
    page_images,
    page_texts,
)
from copilot.documents.schemas import DocumentCitation, ExtractedField, LabDocument, LabResult
from copilot.llm import ScriptedLLM

FIXTURE = Path(__file__).resolve().parent.parent / "evals" / "stage2" / "fixtures" / "documents" / "metro-labs-jane-doe.pdf"
DOC_ID = 412


@pytest.fixture(scope="module")
def pdf() -> bytes:
    return FIXTURE.read_bytes()


def field(value, quote, page=1, name="value", doc_id=DOC_ID, confidence=0.9):
    return ExtractedField(value=value, confidence=confidence,
                          citation=DocumentCitation(source_id=f"doc:{doc_id}", page=page, field=name, quote=quote))


def result(test, value, unit, rng, flag, page):
    return LabResult(
        test_name=field(test, test, page, "test_name"), value=field(value, value, page),
        unit=field(unit, unit, page, "unit"), reference_range=field(rng, rng, page, "reference_range"),
        collection_date=field("2026-09-17", "Collected: 2026-09-17", 1, "collection_date"),
        abnormal_flag=field(flag, flag, page, "abnormal_flag") if flag else ExtractedField.absent(),
    )


def proposed(doc_id=DOC_ID, **overrides) -> LabDocument:
    base = dict(
        source_id=f"doc:{doc_id}", page_count=2,
        patient_ref=field("Jane Doe", "Patient: Jane Doe", 1, "patient_ref", doc_id),
        report_date=field("2026-09-18", "Reported: 2026-09-18", 1, "report_date", doc_id),
        performing_lab=field("Metro Clinical Labs", "METRO CLINICAL LABS", 1, "performing_lab", doc_id),
        ordering_provider=field("Dana Reyes", "Ordering provider: Dana Reyes", 1, "ordering_provider", doc_id),
        results=[result("Potassium", "5.4", "mmol/L", "3.5-5.0", "H", 1),
                 result("Hemoglobin A1c", "7.4", "%", "4.0-5.6", "H", 2)],
    )
    base.update(overrides)
    return LabDocument(**base)


# --- the fixture is a real PDF with a text layer -----------------------------------

def test_fixture_has_two_pages_a_text_layer_and_renders(pdf):
    assert page_count(pdf) == 2
    texts = page_texts(pdf, 6)
    assert "Potassium" in texts[0] and "5.4" in texts[0] and "Hemoglobin A1c" in texts[1]
    images = page_images(pdf, 6)
    assert len(images) == 2 and images[0][:8] == b"\x89PNG\r\n\x1a\n"


# --- what the deterministic checks do to the model's proposal ----------------------

def test_a_faithful_extraction_passes_unchanged(pdf):
    doc, demoted = demote_uncited(proposed(), DOC_ID, page_texts(pdf, 6), 2)
    assert demoted == [] and doc.unsupported() == []


def test_a_quote_not_on_the_page_demotes_that_field(pdf):
    bad = proposed()
    bad.results[0].value = field("5.9", "Potassium 5.9 mmol/L", 1)      # the report says 5.4
    doc, demoted = demote_uncited(bad, DOC_ID, page_texts(pdf, 6), 2)
    assert demoted == ["results[0].value: quote is not on the cited page"]
    assert not doc.results[0].value.supported and doc.results[0].value.confidence == 0
    assert doc.results[0].test_name.supported, "only the field with the bad citation is demoted"


def test_a_citation_to_the_wrong_page_is_demoted(pdf):
    bad = proposed()
    bad.results[1].value = field("7.4", "7.4", page=1)     # A1c is on page 2
    _, demoted = demote_uncited(bad, DOC_ID, page_texts(pdf, 6), 2)
    assert demoted == ["results[1].value: quote is not on the cited page"]
    bad.results[1].value = field("7.4", "7.4", page=3)
    _, demoted = demote_uncited(bad, DOC_ID, page_texts(pdf, 6), 2)
    assert demoted == ["results[1].value: cites page 3 of 2"]


def test_a_citation_to_another_document_is_demoted(pdf):
    bad = proposed()
    bad.patient_ref = field("Jane Doe", "Patient: Jane Doe", 1, "patient_ref", doc_id=999)
    _, demoted = demote_uncited(bad, DOC_ID, page_texts(pdf, 6), 2)
    assert demoted == ["patient_ref: cites a different document"]


def test_a_scanned_page_without_text_layer_cannot_be_checked_and_is_kept():
    doc, demoted = demote_uncited(proposed(), DOC_ID, ["", ""], 2)
    assert demoted == [] and doc.results[0].value.supported


# --- end to end with a scripted model ----------------------------------------------

def test_extract_returns_a_result_with_the_documents_true_bookkeeping(pdf, settings):
    llm = ScriptedLLM([proposed(page_count=9).model_copy(update={"source_id": "doc:1"})])
    out = extract_lab_document(DOC_ID, pdf, llm, settings, "cid-x")
    assert out.doc_id == DOC_ID and out.document.source_id == f"doc:{DOC_ID}" and out.document.page_count == 2
    # the model's citations named doc:412 correctly, so nothing is demoted, only the absent flag is listed
    assert out.unsupported_fields == []
    assert llm.calls == ["structured"] and out.extraction_ms >= 0


def test_extract_demotes_and_lists_an_invented_value(pdf, settings):
    bad = proposed()
    bad.results[0].value = field("5.9", "Potassium 5.9 mmol/L", 1)
    out = extract_lab_document(DOC_ID, pdf, ScriptedLLM([bad]), settings, "cid-y")
    assert "results[0].value: quote is not on the cited page" in out.unsupported_fields
    assert not out.document.results[0].value.supported


def test_extract_reports_an_unreadable_file_without_echoing_it(settings):
    with pytest.raises(ExtractionFailed) as err:
        extract_lab_document(DOC_ID, b"not a pdf at all", ScriptedLLM([]), settings, "cid-z")
    assert "unreadable document" in str(err.value) and "not a pdf" not in str(err.value)


def test_extract_reports_a_model_failure_by_category(pdf, settings):
    with pytest.raises(ExtractionFailed) as err:
        extract_lab_document(DOC_ID, pdf, ScriptedLLM([]), settings, "cid-w")   # nothing scripted: the call raises
    assert str(err.value).startswith("model call failed")


def test_a_value_absent_from_its_own_quote_is_demoted(pdf):
    bad = proposed()
    bad.results[0].value = field("5.4", "Sodium                  140         mmol/L", 1)   # real line, wrong value
    _, demoted = demote_uncited(bad, DOC_ID, page_texts(pdf, 6), 2)
    assert demoted == ["results[0].value: value is not in the cited quote"]
