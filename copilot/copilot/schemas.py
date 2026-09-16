"""Typed contracts shared by the PHP gateway, the agent, the verifier and the evals.

The chart schema is produced by the OpenEMR module (ChartReader.php) and consumed here.
Every record carries a `source_id` ("problem:123", "lab:9911", ...) which is the unit of
citation: a claim is grounded only if it cites source_ids that exist in the active
patient's chart. See evals/GROUNDING_RULES.md.
"""

from __future__ import annotations

from datetime import date
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field


class ResponseState(str, Enum):
    """The four response states of the PRD's failure-mode contract (FR17, FR20)."""

    COMPLETE = "complete"
    PARTIAL = "partial"
    UNABLE = "unable_to_answer"
    DENIED = "access_denied"


class SourceStatus(BaseModel):
    """Outcome of retrieving one data domain from OpenEMR."""

    status: Literal["ok", "empty", "error", "timeout"]
    count: int = 0
    ms: int = 0
    detail: str | None = None


class PatientRef(BaseModel):
    pid: int
    uuid: str
    name: str
    dob: str | None = None
    age: int | None = None
    sex: str | None = None
    pubpid: str | None = None
    provider_id: int | None = None
    source_id: str


class Appointment(BaseModel):
    eid: int | None = None
    date: str | None = None
    time: str | None = None
    title: str | None = None
    status: str | None = None
    source_id: str | None = None


class Problem(BaseModel):
    source_id: str
    uuid: str | None = None
    title: str
    code: str | None = None
    begdate: str | None = None
    enddate: str | None = None
    outcome: str | None = None
    date: str | None = None
    modifydate: str | None = None
    comments: str | None = None


class Medication(BaseModel):
    source_id: str
    uuid: str | None = None
    drug: str
    rxnorm: str | None = None
    dosage: str | None = None
    unit: str | None = None
    interval: str | None = None
    route: str | None = None
    start_date: str | None = None
    end_date: str | None = None
    active: int = 0
    date_added: str | None = None
    note: str | None = None


class Allergy(BaseModel):
    source_id: str
    uuid: str | None = None
    title: str
    reaction: str | None = None
    severity: str | None = None
    begdate: str | None = None
    enddate: str | None = None
    comments: str | None = None


class Lab(BaseModel):
    source_id: str
    uuid: str | None = None
    code: str | None = None
    test: str
    value: str | None = None
    units: str | None = None
    range: str | None = None
    abnormal: str | None = None
    date: str | None = None
    status: str | None = None
    order_name: str | None = None


class Encounter(BaseModel):
    source_id: str
    uuid: str | None = None
    date: str | None = None
    reason: str | None = None
    category: str | None = None
    class_code: str | None = None
    provider: str | None = None
    facility: str | None = None


class Immunization(BaseModel):
    source_id: str
    uuid: str | None = None
    date: str | None = None
    cvx: str | None = None
    name: str | None = None


class VitalsRecord(BaseModel):
    source_id: str
    uuid: str | None = None
    date: str | None = None
    bps: str | None = None
    bpd: str | None = None
    pulse: str | None = None
    height: str | None = None
    weight: str | None = None
    spo2: str | None = None
    bmi: str | None = None
    temperature: str | None = None


class Chart(BaseModel):
    """One patient's compact, field-limited chart as read by the PHP gateway (REQ-MIN-1)."""

    schema_version: str = "1.0"
    generated_at: str
    patient: PatientRef
    appointment: Appointment | None = None
    sources: dict[str, SourceStatus] = Field(default_factory=dict)
    problems: list[Problem] = Field(default_factory=list)
    medications: list[Medication] = Field(default_factory=list)
    allergies: list[Allergy] = Field(default_factory=list)
    labs: list[Lab] = Field(default_factory=list)
    encounters: list[Encounter] = Field(default_factory=list)
    immunizations: list[Immunization] = Field(default_factory=list)
    vitals: list[VitalsRecord] = Field(default_factory=list)

    def index(self) -> dict[str, dict[str, Any]]:
        """source_id -> record, for the verifier. Only this patient's records are here."""
        out: dict[str, dict[str, Any]] = {self.patient.source_id: self.patient.model_dump()}
        if self.appointment and self.appointment.source_id:
            out[self.appointment.source_id] = self.appointment.model_dump()
        for group in (self.problems, self.medications, self.allergies, self.labs,
                      self.encounters, self.immunizations, self.vitals):
            for record in group:
                out[record.source_id] = record.model_dump()
        return out

    def failed_sources(self) -> list[str]:
        return [name for name, s in self.sources.items() if s.status in ("error", "timeout")]


# ---------------------------------------------------------------------------
# Model output contracts (what the LLM must produce) and verified output
# ---------------------------------------------------------------------------

class Claim(BaseModel):
    """One factual statement with the records that support it."""

    text: str = Field(description="One sentence. Values must be copied exactly from the cited records.")
    source_ids: list[str] = Field(default_factory=list, description="source_id values of the supporting records")


class BriefSection(BaseModel):
    key: Literal["primary_diagnosis", "comorbidities", "recent_labs", "compliance", "medications", "allergies", "items_to_inspect"]
    title: str
    claims: list[Claim] = Field(default_factory=list)
    missing: str | None = Field(default=None, description="Plain statement of what is not recorded or unavailable, if anything")


class BriefDraft(BaseModel):
    """The model's draft of the rounding brief, before verification."""

    sections: list[BriefSection]


class TopicCheck(BaseModel):
    """Pre-check of a follow-up question on its own, without conversation history."""

    about_patient_record: bool = Field(
        description="True if the message asks about a patient's medical record or clinical care (labs, medications, "
                    "problems, allergies, visits, vitals, a comparison with earlier values, a treatment or dosing question, "
                    "another patient). False for anything unrelated: weather, greetings, small talk, general knowledge, "
                    "questions about the assistant itself.")


class AnswerDraft(BaseModel):
    """The model's draft answer to a follow-up question, before verification."""

    claims: list[Claim] = Field(default_factory=list)
    missing: str | None = Field(default=None, description="What was looked for and not found, if anything")
    boundary: str | None = Field(
        default=None,
        description="Set when the question asks for a diagnosis, treatment, dose change or order: the product boundary statement",
    )
    off_topic: bool = Field(
        default=False,
        description="True when the question is not about the selected patient's record at all (weather, small talk, general knowledge); then give no claims and put the one-sentence reply in 'missing'",
    )


class Citation(BaseModel):
    source_id: str
    type: str
    label: str
    date: str | None = None


class VerifiedClaim(BaseModel):
    text: str
    source_ids: list[str]


class RemovedClaim(BaseModel):
    text: str
    reason: str


class RuleOutcome(BaseModel):
    rule_id: str
    rule_version: str
    outcome: Literal["pass", "flag", "unable_to_evaluate", "engine_failure"]
    summary: str
    source_ids: list[str] = Field(default_factory=list)


class VerifiedSection(BaseModel):
    key: str
    title: str
    claims: list[VerifiedClaim] = Field(default_factory=list)
    missing: str | None = None


class AgentResponse(BaseModel):
    """What the UI renders. Never contains an unverified claim."""

    correlation_id: str
    state: ResponseState
    state_reason: str
    pid: int
    kind: Literal["brief", "answer"]
    comparison_window: str
    generated_at: str
    sections: list[VerifiedSection] = Field(default_factory=list)
    claims: list[VerifiedClaim] = Field(default_factory=list)
    missing: str | None = None
    boundary: str | None = None
    off_topic: bool = False
    citations: list[Citation] = Field(default_factory=list)
    rule_outcomes: list[RuleOutcome] = Field(default_factory=list)
    removed_claims: list[RemovedClaim] = Field(default_factory=list)
    sources: dict[str, SourceStatus] = Field(default_factory=dict)
    tool_calls: list[str] = Field(default_factory=list)
    iterations: int = 0
    duration_ms: int = 0
    langsmith_run_id: str | None = None


def today_iso(today: date | None = None) -> str:
    return (today or date.today()).isoformat()
