"""Turn raw chart records into what the model is allowed to see (USERS.md REQ-NORM-1).

Applies the AUDIT.md data-quality mitigations before any text reaches the model:
- D1: medication status comes from end_date, never from the `active` flag alone
- D2: medications de-duplicated by RxNorm code
- D3: problems split by SNOMED semantic tag (disorder vs finding/situation), de-duplicated
- D5: "abnormal" only against the versioned demo reference table, labelled as such
- D7: empty lists are "none recorded", never "none"
- D8: default date windows on labs and encounters
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from .reference_data import (
    INFLUENZA_CVX,
    REFERENCE_RANGES,
    REVIEW_DUE_PATTERNS,
    RULES_VERSION,
    SCREENING_SCORE_CODES,
)
from .schemas import Chart, Encounter, Immunization, Lab, Medication, Problem

_TAG = re.compile(r"\((disorder|finding|situation|procedure|event|regime/therapy|person|observable entity)\)\s*$", re.I)
_EMPTY_DATES = {"", "0000-00-00", "0000-00-00 00:00:00", None}


def parse_date(value: str | None) -> date | None:
    if value in _EMPTY_DATES:
        return None
    text = str(value)[:10]
    try:
        return datetime.strptime(text, "%Y-%m-%d").date()
    except ValueError:
        return None


def problem_kind(title: str) -> str:
    match = _TAG.search(title or "")
    return match.group(1).lower() if match else "unspecified"


def clean_title(title: str) -> str:
    return _TAG.sub("", title or "").strip()


def display_name(name: str) -> str:
    """Synthea names carry numeric suffixes (AUDIT D6): 'Judie557 Abernathy524' -> 'Judie Abernathy'."""
    return re.sub(r"\d+", "", name or "").strip()


# ---------------------------------------------------------------------------
# Problems
# ---------------------------------------------------------------------------

def is_active_problem(problem: Problem, today: date) -> bool:
    end = parse_date(problem.enddate)
    return end is None or end >= today


def active_problems(chart: Chart, today: date, kind: str = "disorder") -> list[Problem]:
    """Active problems of one semantic kind, de-duplicated by code keeping the most recent onset."""
    seen: dict[str, Problem] = {}
    for problem in chart.problems:
        if not is_active_problem(problem, today):
            continue
        if kind != "all" and problem_kind(problem.title) != kind:
            continue
        key = problem.code or clean_title(problem.title).lower()
        current = seen.get(key)
        if current is None or (parse_date(problem.begdate) or date.min) > (parse_date(current.begdate) or date.min):
            seen[key] = problem
    return sorted(seen.values(), key=lambda p: parse_date(p.begdate) or date.min, reverse=True)


# ---------------------------------------------------------------------------
# Medications
# ---------------------------------------------------------------------------

def medication_status(med: Medication, today: date) -> tuple[str, str]:
    """(status, explanation). Status is derived from dates first (AUDIT D1)."""
    end = parse_date(med.end_date)
    if end is not None and end < today:
        if med.active:
            return "ended", f"end date {end.isoformat()} has passed although the record is still flagged active; status uncertain"
        return "ended", f"ended {end.isoformat()}"
    if end is not None:
        return "active", f"active until {end.isoformat()}"
    if med.active:
        return "active", "active; no end date recorded"
    return "stopped", "stopped; no end date recorded"


def medications_with_status(chart: Chart, today: date) -> list[tuple[Medication, str, str]]:
    """De-duplicate by RxNorm (AUDIT D2), keep the most recently added, and attach the derived status."""
    seen: dict[str, Medication] = {}
    for med in chart.medications:
        key = med.rxnorm or med.drug.lower()
        current = seen.get(key)
        if current is None or (parse_date(med.date_added) or date.min) > (parse_date(current.date_added) or date.min):
            seen[key] = med
    rows = [(m, *medication_status(m, today)) for m in seen.values()]
    order = {"active": 0, "ended": 1, "stopped": 2}
    return sorted(rows, key=lambda r: (order.get(r[1], 3), r[0].drug.lower()))


def active_medications(chart: Chart, today: date) -> list[Medication]:
    return [m for m, status, _ in medications_with_status(chart, today) if status == "active"]


def strength_mg(drug: str) -> float | None:
    """Parse the first 'NNN MG' in an RxNorm display name (e.g. 'Acetaminophen 325 MG Oral Tablet')."""
    match = re.search(r"(\d+(?:\.\d+)?)\s*MG\b(?!/)", drug or "", re.I)
    return float(match.group(1)) if match else None


# ---------------------------------------------------------------------------
# Labs
# ---------------------------------------------------------------------------

@dataclass
class LabFlag:
    lab: Lab
    outcome: str            # "in_range" | "out_of_range" | "not_evaluated"
    reference: str | None   # "3.5-5.0 mmol/L (demo reference demo-rules-...)"
    direction: str | None   # "high" | "low" | None


def numeric_value(lab: Lab) -> float | None:
    try:
        return float(str(lab.value).strip())
    except (TypeError, ValueError):
        return None


def flag_against_reference(lab: Lab) -> LabFlag:
    """Compare a result with the demo reference table. Never derives a severity (PRD lab-range boundary)."""
    if lab.range:
        # The record carries its own range: prefer it and do not overlay the demo table.
        return LabFlag(lab, "not_evaluated", f"recorded range {lab.range}", None)
    code = lab.code or ""
    value = numeric_value(lab)
    if code in SCREENING_SCORE_CODES or code not in REFERENCE_RANGES or value is None:
        return LabFlag(lab, "not_evaluated", None, None)
    low, high, unit = REFERENCE_RANGES[code]
    reference = f"{low:g}-{high:g} {unit} (demo reference {RULES_VERSION}, not from the record)"
    if value < low:
        return LabFlag(lab, "out_of_range", reference, "low")
    if value > high:
        return LabFlag(lab, "out_of_range", reference, "high")
    return LabFlag(lab, "in_range", reference, None)


def labs_since(chart: Chart, today: date, days: int) -> list[Lab]:
    cutoff = today - timedelta(days=days)
    rows = [lab for lab in chart.labs if (parse_date(lab.date) or date.min) >= cutoff]
    return sorted(rows, key=lambda lab: (parse_date(lab.date) or date.min, lab.test), reverse=True)


def latest_lab_date(chart: Chart) -> date | None:
    dates = [parse_date(lab.date) for lab in chart.labs]
    dates = [d for d in dates if d is not None]
    return max(dates) if dates else None


def latest_per_test(chart: Chart) -> list[Lab]:
    seen: dict[str, Lab] = {}
    for lab in chart.labs:
        key = lab.code or lab.test
        current = seen.get(key)
        if current is None or (parse_date(lab.date) or date.min) > (parse_date(current.date) or date.min):
            seen[key] = lab
    return sorted(seen.values(), key=lambda lab: (parse_date(lab.date) or date.min), reverse=True)


def recent_lab_flags(chart: Chart, today: date, days: int) -> tuple[list[LabFlag], list[Lab], str]:
    """Flags for recent labs, the labs considered, and a plain-language window statement."""
    recent = labs_since(chart, today, days)
    if recent:
        window = f"results collected in the last {days} days"
    else:
        last = latest_lab_date(chart)
        if last is None:
            return [], [], "no laboratory results recorded"
        # Nothing recent: fall back to the most recent collection date so the brief is still useful.
        recent = [lab for lab in chart.labs if parse_date(lab.date) == last]
        window = f"no results in the last {days} days; showing the most recent collection ({last.isoformat()})"
    flags = [flag_against_reference(lab) for lab in recent]
    return flags, recent, window


# ---------------------------------------------------------------------------
# Encounters, immunizations, compliance
# ---------------------------------------------------------------------------

def encounters_since(chart: Chart, today: date, days: int) -> list[Encounter]:
    cutoff = today - timedelta(days=days)
    rows = [e for e in chart.encounters if (parse_date(e.date) or date.min) >= cutoff]
    return sorted(rows, key=lambda e: parse_date(e.date) or date.min, reverse=True)


def latest_encounter(chart: Chart) -> Encounter | None:
    rows = sorted(chart.encounters, key=lambda e: parse_date(e.date) or date.min, reverse=True)
    return rows[0] if rows else None


def last_influenza(chart: Chart) -> Immunization | None:
    rows = [i for i in chart.immunizations if (i.cvx or "") in INFLUENZA_CVX]
    rows = sorted(rows, key=lambda i: parse_date(i.date) or date.min, reverse=True)
    return rows[0] if rows else None


@dataclass
class ComplianceSignal:
    kind: str
    text: str
    source_ids: list[str] = field(default_factory=list)


def compliance_signals(chart: Chart, today: date) -> list[ComplianceSignal]:
    """Care-plan adherence signals, each cited. Absence of a signal is not a finding."""
    signals: list[ComplianceSignal] = []

    for problem in active_problems(chart, today, kind="all"):
        if any(p in problem.title.lower() for p in REVIEW_DUE_PATTERNS):
            since = parse_date(problem.begdate)
            age = f" (recorded {since.isoformat()})" if since else ""
            signals.append(ComplianceSignal("review_due", f"{clean_title(problem.title)} is recorded as an open item{age}", [problem.source_id]))

    for med, status, explanation in medications_with_status(chart, today):
        if status == "ended" and med.active:
            signals.append(ComplianceSignal(
                "medication_status_uncertain",
                f"{med.drug}: {explanation}", [med.source_id]))

    last = latest_encounter(chart)
    disorders = active_problems(chart, today, kind="disorder")
    if last is not None and disorders:
        last_date = parse_date(last.date)
        if last_date is not None and (today - last_date).days > 365:
            signals.append(ComplianceSignal(
                "follow_up_gap",
                f"last recorded encounter was {last_date.isoformat()} ({(today - last_date).days} days ago) with {len(disorders)} active disorder(s) on the problem list",
                [last.source_id] + [d.source_id for d in disorders[:3]]))

    flu = last_influenza(chart)
    if flu is None:
        if chart.immunizations:
            signals.append(ComplianceSignal("immunization_gap", "no seasonal influenza vaccine recorded", [chart.immunizations[0].source_id]))
    else:
        flu_date = parse_date(flu.date)
        if flu_date is not None and (today - flu_date).days > 365:
            signals.append(ComplianceSignal("immunization_gap", f"last influenza vaccine recorded {flu_date.isoformat()}", [flu.source_id]))

    return signals


# ---------------------------------------------------------------------------
# Primary diagnosis candidate (documented, never inferred)
# ---------------------------------------------------------------------------

def primary_diagnosis_candidate(chart: Chart, today: date) -> tuple[Problem | None, str, list[str]]:
    """The documented problem the brief should lead with, and the rule that chose it.

    Rule 1: an active disorder whose title matches the most recent encounter's reason.
    Rule 2: otherwise the most recently recorded active disorder.
    Returns (problem, basis, extra source ids). No problem -> (None, explanation, []).
    """
    disorders = active_problems(chart, today, kind="disorder")
    if not disorders:
        return None, "no active disorder on the problem list", []
    last = latest_encounter(chart)
    if last is not None and last.reason:
        reason = last.reason.lower()
        for problem in disorders:
            title = clean_title(problem.title).lower()
            if title and (title in reason or reason in title):
                return problem, f"matches the reason for the most recent encounter ({last.date})", [last.source_id]
    return disorders[0], "most recently recorded active disorder (no encounter reason matched)", []
