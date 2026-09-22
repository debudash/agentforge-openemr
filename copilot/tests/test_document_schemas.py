"""The document schemas: an extracted fact is supported or unsupported, never in between."""

import pytest
from pydantic import ValidationError

from copilot.documents.schemas import (
    Demographics,
    DocumentCitation,
    ExtractedField,
    ExtractionResult,
    IntakeForm,
    LabDocument,
    LabResult,
)
from copilot.schemas import Citation, source_type_for


def cite(field="value", quote="Potassium 5.4 mmol/L", page=2):
    return DocumentCitation(source_id="doc:412", page=page, field=field, quote=quote)


def supported(value, **kw):
    return ExtractedField(value=value, confidence=kw.pop("confidence", 0.9), citation=cite(**kw))


# --- the supported / unsupported invariant --------------------------------------

def test_supported_field_needs_value_citation_and_confidence():
    field = supported("5.4")
    assert field.supported and field.citation.page_or_section() == "p2"


def test_unsupported_field_is_null_with_confidence_zero_and_no_citation():
    field = ExtractedField.absent()
    assert not field.supported and field.confidence == 0 and field.citation is None


@pytest.mark.parametrize("kwargs", [
    {"value": "5.4", "confidence": 0.9, "citation": None},          # a value with no evidence
    {"value": "5.4", "confidence": 0.0, "citation": cite()},         # evidence but no confidence
    {"value": None, "confidence": 0.5, "citation": None},            # confidence in nothing
    {"value": None, "confidence": 0.0, "citation": cite()},          # a citation for a null
    {"value": "5.4", "confidence": 1.5, "citation": cite()},         # out of range
])
def test_anything_in_between_cannot_validate(kwargs):
    with pytest.raises(ValidationError):
        ExtractedField(**kwargs)


# --- the citation names document, page, field and quote ---------------------------

@pytest.mark.parametrize("kwargs", [
    {"source_id": "lab:6001", "page": 1, "field": "value", "quote": "x"},   # not a document id
    {"source_id": "doc:412", "page": 0, "field": "value", "quote": "x"},    # pages start at 1
    {"source_id": "doc:412", "page": 1, "field": "", "quote": "x"},
    {"source_id": "doc:412", "page": 1, "field": "value", "quote": ""},     # no quote, no evidence
])
def test_document_citation_rejects_incomplete_evidence(kwargs):
    with pytest.raises(ValidationError):
        DocumentCitation(**kwargs)


# --- whole documents ---------------------------------------------------------------

def lab_document(abnormal=None):
    return LabDocument(
        source_id="doc:412", page_count=2,
        patient_ref=supported("Jane Doe, DOB 1962-04-03", field="patient", page=1),
        report_date=supported("2026-09-18", field="report_date", page=1),
        performing_lab=supported("Metro Clinical Labs", field="performing_lab", page=1),
        ordering_provider=ExtractedField.absent(),
        results=[LabResult(
            test_name=supported("Potassium", field="test_name"),
            value=supported("5.4"),
            unit=supported("mmol/L", field="unit"),
            reference_range=supported("3.5-5.0", field="reference_range"),
            collection_date=supported("2026-09-17", field="collection_date"),
            abnormal_flag=abnormal or supported("H", field="abnormal_flag"),
        )],
    )


def test_lab_document_lists_every_unsupported_field_by_path():
    doc = lab_document(abnormal=ExtractedField.absent())
    assert doc.unsupported() == ["ordering_provider", "results[0].abnormal_flag"]


def test_lab_document_round_trips_through_json():
    doc = lab_document()
    again = LabDocument.model_validate_json(doc.model_dump_json())
    assert again == doc and again.results[0].value.citation.quote == "Potassium 5.4 mmol/L"


def test_intake_form_lists_unsupported_list_items():
    form = IntakeForm(
        source_id="doc:413", page_count=1,
        form_date=supported("2026-09-16", field="form_date", page=1),
        demographics=Demographics(name=supported("Jane Doe", field="name", page=1),
                                  dob=ExtractedField.absent(), sex=supported("F", field="sex", page=1)),
        chief_concern=supported("headaches for two weeks", field="chief_concern", page=1),
        current_medications=[supported("lisinopril 10 mg", field="medication", page=1), ExtractedField.absent()],
        allergies=[],
        family_history=[supported("father: hypertension", field="family_history", page=1)],
    )
    assert form.unsupported() == ["demographics.dob", "current_medications[1]"]


def test_extraction_result_discriminates_on_doc_type():
    doc = lab_document()
    result = ExtractionResult(doc_id=412, doc_type="lab_pdf", document=doc, model="test", unsupported_fields=doc.unsupported())
    assert isinstance(result.document, LabDocument) and result.unsupported_fields == ["ordering_provider"]
    with pytest.raises(ValidationError):
        ExtractionResult(doc_id=412, doc_type="intake_form", document={**doc.model_dump(), "doc_type": "lab_pdf"}, model="test")


# --- the citation contract v2 keeps Week 1 citations valid --------------------------

def test_week1_citation_reads_as_a_record_with_v2_fields_null():
    c = Citation(source_id="lab:6001", type="lab", label="Potassium: 5.4 mmol/L", date="2026-08-16")
    assert c.source_type == "record"
    assert c.page_or_section is None and c.field_or_chunk_id is None and c.quote_or_value is None


@pytest.mark.parametrize("source_id,expected", [
    ("lab:6001", "record"), ("problem:9001", "record"), ("patient:101", "record"),
    ("rule:ALLERGY-1", "rule"), ("signal:1", "signal"), ("empty:labs", "empty"),
    ("doc:412", "document"), ("guideline:uspstf-htn-2021", "guideline"),
])
def test_source_type_follows_the_id_prefix(source_id, expected):
    assert source_type_for(source_id) == expected
    assert Citation(source_id=source_id, type="x", label="x").source_type == expected


def test_a_citation_cannot_claim_a_source_type_its_id_contradicts():
    with pytest.raises(ValidationError):
        Citation(source_id="lab:6001", type="lab", label="x", source_type="guideline")


def test_document_citation_carries_page_and_quote():
    c = Citation(source_id="doc:412", type="doc", label="lab_pdf metro-labs.pdf",
                 page_or_section="p2", field_or_chunk_id="results[0].value", quote_or_value="Potassium 5.4 mmol/L")
    assert c.source_type == "document" and c.page_or_section == "p2"


def test_the_models_wording_of_doc_type_never_fails_an_otherwise_good_extraction():
    """A correct reading was thrown away because the model answered "LAB_REPORT" for doc_type.

    doc_type is the caller's fact -- which document this is was settled before the model saw a
    page -- and extract_document overwrites it with the authoritative value straight after
    parsing. So the model's wording of it must never decide whether the extraction survives.
    """
    from copilot.documents.schemas import IntakeForm, LabDocument

    absent = {"value": None, "confidence": 0}
    lab = LabDocument.model_validate({
        "doc_type": "LAB_REPORT", "source_id": "doc:1", "page_count": 2, "patient_ref": absent,
        "report_date": absent, "performing_lab": absent, "ordering_provider": absent, "results": [],
    })
    assert lab.doc_type == "lab_pdf"

    intake = IntakeForm.model_validate({
        "doc_type": "Patient Intake", "source_id": "doc:2", "page_count": 1, "form_date": absent,
        "chief_concern": absent, "demographics": {"name": absent, "dob": absent, "sex": absent},
    })
    assert intake.doc_type == "intake_form"
