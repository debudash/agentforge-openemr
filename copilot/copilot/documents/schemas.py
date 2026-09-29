"""Strict schemas for extracted documents (Week 2 requirement 2).

Two rules the types enforce, so no prompt has to:

1. A field is supported or unsupported, never in between. Supported means a value, a citation
   into the document and confidence above zero. Unsupported means null, no citation, confidence
   exactly zero. A value with no citation, or a citation on a null value, fails validation.
2. Every citation names the document, the page, the field and the quote it was read from.

Values are strings copied from the page, not parsed. Parsing happens when a value is persisted,
and the persisted row is what the verifier checks against (rule 3).
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

DocType = Literal["lab_pdf", "intake_form"]


class DocumentCitation(BaseModel):
    """Where in a stored document a fact was read. bbox is derived later from the text layer."""

    source_id: str = Field(pattern=r"^doc:\d+$")
    page: int = Field(ge=1)
    field: str = Field(min_length=1)
    quote: str = Field(min_length=1, description="The text on the page the value was read from")
    bbox: tuple[float, float, float, float] | None = None

    def page_or_section(self) -> str:
        return f"p{self.page}"


class ExtractedField(BaseModel):
    """One fact read from a document, with the evidence for it or an explicit absence."""

    value: str | None = None
    confidence: float = Field(ge=0.0, le=1.0)
    citation: DocumentCitation | None = None

    @model_validator(mode="after")
    def _supported_or_unsupported(self) -> "ExtractedField":
        supported = self.value is not None and self.citation is not None and self.confidence > 0
        unsupported = self.value is None and self.citation is None and self.confidence == 0
        if not (supported or unsupported):
            raise ValueError(
                "an extracted field is either supported (value, citation, confidence > 0) "
                "or unsupported (null, no citation, confidence 0)"
            )
        return self

    @property
    def supported(self) -> bool:
        return self.value is not None

    @classmethod
    def absent(cls) -> "ExtractedField":
        return cls(value=None, confidence=0.0, citation=None)


def _unsupported_paths(prefix: str, fields: dict[str, ExtractedField]) -> list[str]:
    return [f"{prefix}{name}" for name, field in fields.items() if not field.supported]


class LabResult(BaseModel):
    test_name: ExtractedField
    value: ExtractedField
    unit: ExtractedField
    reference_range: ExtractedField
    collection_date: ExtractedField
    abnormal_flag: ExtractedField = Field(
        description="What the report itself says (H, L, N, blank). Data, not a constraint judgement: "
                    "only the rule engine may call a value abnormal in a response (rule 7).")

    def fields(self) -> dict[str, ExtractedField]:
        return {"test_name": self.test_name, "value": self.value, "unit": self.unit,
                "reference_range": self.reference_range, "collection_date": self.collection_date,
                "abnormal_flag": self.abnormal_flag}


class LabDocument(BaseModel):
    doc_type: Literal["lab_pdf"] = "lab_pdf"
    source_id: str = Field(pattern=r"^doc:\d+$")
    page_count: int = Field(ge=1)
    patient_ref: ExtractedField = Field(description="The patient as printed on the report, for the cross-check")
    report_date: ExtractedField
    performing_lab: ExtractedField
    ordering_provider: ExtractedField = Field(description="Drives order attribution: exact match to the signed-in user or the import provider")
    results: list[LabResult] = Field(default_factory=list)

    # doc_type is the caller's fact, not the model's: which document this is was settled before
    # the model was asked anything, and extract_document overwrites source_id and page_count with
    # the authoritative values straight after parsing. Validating the model's *wording* of it only
    # creates a way to throw away a correct reading -- gemini-2.5-flash-lite answers "LAB_REPORT",
    # which is right, and failed the whole extraction. Accept what it wrote, then use ours.
    @model_validator(mode="before")
    @classmethod
    def _doc_type_is_ours(cls, data: Any) -> Any:
        if isinstance(data, dict):
            return {**data, "doc_type": "lab_pdf"}
        return data

    def unsupported(self) -> list[str]:
        out = _unsupported_paths("", {"patient_ref": self.patient_ref, "report_date": self.report_date,
                                      "performing_lab": self.performing_lab, "ordering_provider": self.ordering_provider})
        for i, result in enumerate(self.results):
            out += _unsupported_paths(f"results[{i}].", result.fields())
        return out


class Demographics(BaseModel):
    name: ExtractedField
    dob: ExtractedField
    sex: ExtractedField

    def fields(self) -> dict[str, ExtractedField]:
        return {"name": self.name, "dob": self.dob, "sex": self.sex}


class IntakeForm(BaseModel):
    doc_type: Literal["intake_form"] = "intake_form"
    source_id: str = Field(pattern=r"^doc:\d+$")
    page_count: int = Field(ge=1)
    form_date: ExtractedField
    demographics: Demographics
    chief_concern: ExtractedField
    current_medications: list[ExtractedField] = Field(default_factory=list)
    allergies: list[ExtractedField] = Field(default_factory=list)
    family_history: list[ExtractedField] = Field(default_factory=list)

    # doc_type is the caller's fact, not the model's: which document this is was settled before
    # the model was asked anything, and extract_document overwrites source_id and page_count with
    # the authoritative values straight after parsing. Validating the model's *wording* of it only
    # creates a way to throw away a correct reading -- gemini-2.5-flash-lite answers "LAB_REPORT",
    # which is right, and failed the whole extraction. Accept what it wrote, then use ours.
    @model_validator(mode="before")
    @classmethod
    def _doc_type_is_ours(cls, data: Any) -> Any:
        if isinstance(data, dict):
            return {**data, "doc_type": "intake_form"}
        return data

    def unsupported(self) -> list[str]:
        out = _unsupported_paths("", {"form_date": self.form_date, "chief_concern": self.chief_concern})
        out += _unsupported_paths("demographics.", self.demographics.fields())
        for name, items in (("current_medications", self.current_medications),
                            ("allergies", self.allergies), ("family_history", self.family_history)):
            out += [f"{name}[{i}]" for i, item in enumerate(items) if not item.supported]
        return out


ExtractedDocument = LabDocument | IntakeForm


class ExtractionResult(BaseModel):
    """What attach_and_extract returns. The module persists from this; the agent never writes."""

    doc_id: int
    doc_type: DocType
    document: ExtractedDocument = Field(discriminator="doc_type")
    unsupported_fields: list[str] = Field(default_factory=list)
    model: str
    extraction_ms: int = 0

    @model_validator(mode="after")
    def _doc_type_agrees(self) -> "ExtractionResult":
        if self.document.doc_type != self.doc_type:
            raise ValueError(f"doc_type {self.doc_type!r} does not match the document ({self.document.doc_type!r})")
        if f"doc:{self.doc_id}" != self.document.source_id:
            raise ValueError(f"doc_id {self.doc_id} does not match the document's source_id {self.document.source_id!r}")
        return self
