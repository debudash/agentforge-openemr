"""The claim verifier (PRD FR8, claim verification policy steps 2-5).

Deterministic and model-free. A claim survives only if:
1. it cites at least one source_id,
2. every cited source_id exists in the active patient's chart index (a record from any
   other patient is, by construction, absent from the index),
3. every number it states appears in the cited records (dates, values, units, doses),
   apart from a small allowlist the caller supplies (today's date, the comparison
   window, the patient's age) and small integer counts,
4. it does not phrase a clinical recommendation (product boundary, USERS.md NG-2).

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


def check_claim(claim: Claim, index: dict[str, dict[str, Any]], allowed_numbers: set[str],
                turn_ids: set[str] | None = None) -> str | None:
    """Return a removal reason, or None when the claim is supported.

    `index` is the active patient's whole chart. When `turn_ids` is given, a claim must also
    cite only records that a tool returned in this turn: a fact restated from memory without
    a fresh lookup is not grounded in this turn, even though the record is the patient's.
    """
    text = (claim.text or "").strip()
    if not text:
        return "empty claim"
    if not claim.source_ids:
        return "no source cited"
    missing = [sid for sid in claim.source_ids if sid not in index]
    if missing:
        return f"cites records that are not in this patient's chart: {', '.join(missing)}"
    if turn_ids is not None:
        stale = [sid for sid in claim.source_ids if sid not in turn_ids]
        if stale:
            return f"cites records no tool returned in this turn (restated without a lookup): {', '.join(stale)}"
    if _RECOMMENDATION.search(text):
        return "phrases a clinical recommendation or diagnosis (product boundary)"
    evidence: set[str] = set()
    for sid in claim.source_ids:
        evidence |= _record_numbers(index[sid])
    unsupported = []
    for number in numbers_in(text):
        if number in evidence or number in allowed_numbers:
            continue
        try:
            value = float(number)
        except ValueError:
            continue
        if value.is_integer() and 0 <= value <= _SMALL_COUNT_MAX:
            continue  # small counts ("3 active medications") are not record values
        unsupported.append(number)
    if unsupported:
        return f"value(s) not found in the cited records: {', '.join(unsupported)}"
    return None


def verify_claims(claims: list[Claim], index: dict[str, dict[str, Any]],
                  allowed_numbers: set[str] | None = None,
                  turn_ids: set[str] | None = None) -> tuple[list[VerifiedClaim], list[RemovedClaim]]:
    kept: list[VerifiedClaim] = []
    removed: list[RemovedClaim] = []
    allowed = allowed_numbers or set()
    for claim in claims:
        reason = check_claim(claim, index, allowed, turn_ids)
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
        out.append(Citation(source_id=sid, type=kind, label=_label(kind, record), date=str(date_value)[:10] if date_value else None))
    return out
