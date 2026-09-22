"""The claim verifier (PRD FR8, claim verification policy steps 2-5).

Deterministic and model-free. A claim survives only if:
1. it cites at least one source_id,
2. every cited source_id exists in the active patient's chart index (a record from any
   other patient is, by construction, absent from the index),
3. every number it states appears in the cited records (dates, values, units, doses),
   apart from a small allowlist the caller supplies (today's date, the comparison
   window, the patient's age) and small integer counts,
4. it does not phrase a clinical recommendation (product boundary, USER.md NG-2).

Anything else is removed and reported, never silently dropped (FR20).
"""

from __future__ import annotations

import re
from typing import Any

from .schemas import (
    BriefDraft,
    Citation,
    Claim,
    RemovedClaim,
    VerifiedClaim,
    VerifiedSection,
    source_type_for,
)

_NUMBER = re.compile(r"(?<![\w.])(\d+(?:\.\d+)?)(?![\w.]|\s*%?\s*(?:of|x|times)\b)")
_RECOMMENDATION = re.compile(
    r"\b(?:you should|i recommend|we recommend|recommend(?:ed|s|ing)?|"
    r"should (?:be )?(?:start|stop|increase|decrease|switch|prescribe|order|discontinue|hold|titrate)|"
    r"consider (?:starting|stopping|switching|increasing|decreasing|adding|prescribing|ordering)|"
    r"start (?:him|her|them|the patient) on|needs? to be (?:started|stopped|increased|decreased)|"
    r"the diagnosis is likely|most likely diagnosis|i would diagnose|prescribe)\b",
    re.I,
)
# Evidence entries quote guidance that says "recommends"; that is attribution, not advice to this
# patient. Only direct, second-person or prescriptive phrasing is barred there (rule 4, rule 12).
_DIRECT_ADVICE = re.compile(
    r"\b(?:you should|i recommend|we recommend|i would recommend|start (?:him|her|them|the patient) on|"
    r"the diagnosis is likely|most likely diagnosis|i would diagnose)\b",
    re.I,
)
_SMALL_COUNT_MAX = 12


def _norm(number: str) -> str:
    try:
        return f"{float(number):g}"
    except ValueError:
        return number


def numbers_in(text: str) -> set[str]:
    return {_norm(m) for m in _NUMBER.findall(text or "")}


def record_text(record: dict[str, Any]) -> str:
    return " ".join(str(v) for v in record.values() if v not in (None, ""))


def _record_numbers(record: dict[str, Any]) -> set[str]:
    found = numbers_in(record_text(record))
    # Dates: allow day/month/year parts and the ISO form so "25 August 2026" and "2026-08-25" both verify.
    for value in record.values():
        match = re.match(r"^(\d{4})-(\d{2})-(\d{2})", str(value or ""))
        if match:
            found |= {match.group(1), _norm(match.group(2)), _norm(match.group(3))}
    return found


def removal_reason_code(reason: str) -> str:
    """Stable code for a removal reason, so removals can be counted by cause.

    Lives beside the reasons it classifies: a reason reworded in check_claim and a mapping kept
    somewhere else would drift apart silently, and the count would quietly become 'other'.
    """
    text = (reason or "").lower()
    if text.startswith("no source cited"):
        return "no_citation"
    if text.startswith("cites records that are not"):
        return "wrong_patient"
    if text.startswith("cites records no tool returned"):
        return "restated_without_lookup"
    if text.startswith("cites guideline evidence only"):
        return "guideline_only"
    if text.startswith("evidence claim cites no guideline"):
        return "evidence_without_guideline"
    if text.startswith("phrases a clinical recommendation"):
        return "recommendation"
    if text.startswith("value(s) not found"):
        return "unsupported_value"
    if text.startswith("empty claim"):
        return "empty_claim"
    if text.startswith("off-topic"):
        return "off_topic"
    return "other"


def check_claim(claim: Claim, index: dict[str, dict[str, Any]], allowed_numbers: set[str],
                turn_ids: set[str] | None = None, allow_guideline_only: bool = False) -> str | None:
    """Return a removal reason, or None when the claim is supported.

    `index` is the active patient's whole chart. When `turn_ids` is given, a claim must also
    cite only records that a tool returned in this turn: a fact restated from memory without
    a fresh lookup is not grounded in this turn, even though the record is the patient's.

    Guideline evidence is not a patient record (rule 1, Week 2). A claim citing only
    `guideline:` ids is removed unless the caller says this section is the evidence section.
    """
    text = (claim.text or "").strip()
    if not text:
        return "empty claim"
    if not claim.source_ids:
        return "no source cited"
    missing = [sid for sid in claim.source_ids if sid not in index]
    if missing:
        return f"cites records that are not in this patient's chart: {', '.join(missing)}"
    if not allow_guideline_only and all(source_type_for(sid) == "guideline" for sid in claim.source_ids):
        return "cites guideline evidence only; a claim about this patient must cite a record, document or rule"
    if turn_ids is not None:
        stale = [sid for sid in claim.source_ids if sid not in turn_ids]
        if stale:
            return f"cites records no tool returned in this turn (restated without a lookup): {', '.join(stale)}"
    if (_DIRECT_ADVICE if allow_guideline_only else _RECOMMENDATION).search(text):
        return "phrases a clinical recommendation or diagnosis (product boundary)"
    evidence: set[str] = set()
    for sid in claim.source_ids:
        evidence |= _record_numbers(index[sid])
    unsupported = []
    for match in _NUMBER.finditer(text):
        raw = match.group(1)
        number = _norm(raw)
        if number in evidence or number in allowed_numbers:
            continue
        try:
            value = float(number)
        except ValueError:
            continue
        # Small counts ("3 active medications") are not record values. A decimal ("7.0") or a
        # percentage ("7%") is a measured value however small, and must be in the cited record.
        count_like = "." not in raw and not text[match.end():match.end() + 2].lstrip().startswith("%")
        if count_like and value.is_integer() and 0 <= value <= _SMALL_COUNT_MAX:
            continue
        if raw not in unsupported:
            unsupported.append(raw)   # reported as written ("7.0"), not normalised
    if unsupported:
        return f"value(s) not found in the cited records: {', '.join(unsupported)}"
    return None


def verify_claims(claims: list[Claim], index: dict[str, dict[str, Any]],
                  allowed_numbers: set[str] | None = None,
                  turn_ids: set[str] | None = None,
                  allow_guideline_only: bool = False) -> tuple[list[VerifiedClaim], list[RemovedClaim]]:
    kept: list[VerifiedClaim] = []
    removed: list[RemovedClaim] = []
    allowed = allowed_numbers or set()
    for claim in claims:
        reason = check_claim(claim, index, allowed, turn_ids, allow_guideline_only)
        if reason is None:
            kept.append(VerifiedClaim(text=claim.text.strip(), source_ids=list(dict.fromkeys(claim.source_ids))))
        else:
            removed.append(RemovedClaim(text=claim.text, reason=reason))
    return kept, removed


def verify_brief(draft: BriefDraft, index: dict[str, dict[str, Any]],
                 allowed_numbers: set[str] | None = None) -> tuple[list[VerifiedSection], list[RemovedClaim]]:
    sections: list[VerifiedSection] = []
    removed_all: list[RemovedClaim] = []
    for section in draft.sections:
        kept, removed = verify_claims(section.claims, index, allowed_numbers)
        removed_all += removed
        sections.append(VerifiedSection(key=section.key, title=section.title, claims=kept, missing=section.missing))
    return sections, removed_all


def _label(kind: str, record: dict[str, Any]) -> str:
    match kind:
        case "problem":
            return str(record.get("title", ""))
        case "prescription" | "medication":
            return str(record.get("drug", ""))
        case "allergy":
            return str(record.get("title", ""))
        case "lab":
            return f"{record.get('test', '')}: {record.get('value', '')} {record.get('units', '') or ''}".strip()
        case "encounter":
            return f"{record.get('category') or 'encounter'}: {record.get('reason') or ''}".strip(": ")
        case "immunization":
            return str(record.get("name") or record.get("cvx", ""))
        case "vitals":
            return "vital signs"
        case "patient":
            return "patient record"
        case "appointment":
            return str(record.get("title") or "appointment")
        case "empty":
            return f"no {record.get('source', '')} records returned"
        case "rule":
            return f"{record.get('rule_id', '')}: {record.get('outcome', '')}"
        case "signal":
            return str(record.get("text", ""))[:80]
        case "doc":
            return f"{record.get('doc_type', 'document')} {record.get('name', '')}".strip()
        case "guideline":
            return f"{record.get('title', '')} {record.get('section', '')}".strip()
        case _:
            return kind


def citations_for(source_ids: list[str], index: dict[str, dict[str, Any]]) -> list[Citation]:
    out: list[Citation] = []
    for sid in dict.fromkeys(source_ids):
        record = index.get(sid)
        if record is None:
            continue
        kind = sid.split(":", 1)[0]
        date_value = record.get("date") or record.get("begdate") or record.get("date_added") or record.get("dob")
        page_or_section = record.get("page_or_section")
        field_or_chunk_id = record.get("field_or_chunk_id")
        quote_or_value = record.get("quote_or_value")
        if record.get("document_id") and record.get("page"):
            # A chart row read from a document: the citation opens the page it was read from.
            page_or_section = f"p{record['page']}"
            field_or_chunk_id = f"doc:{record['document_id']}"
            quote_or_value = f"{record.get('test', '')} {record.get('value', '')} {record.get('units') or ''}".strip()
        out.append(Citation(
            source_id=sid, type=kind, label=_label(kind, record),
            date=str(date_value)[:10] if date_value else None,
            source_type=source_type_for(sid),
            page_or_section=page_or_section,
            field_or_chunk_id=field_or_chunk_id,
            quote_or_value=quote_or_value,
        ))
    return out
