"""The bounded deterministic clinical constraint engine (PRD FR16, decision D007).

One versioned rule pipeline that runs outside the language model. It verifies only the
small rule set tied to the demo dataset and its evaluation cases; it is not clinical
decision support. Every rule returns pass, flag, unable_to_evaluate or engine_failure,
and cites the records it used. The model cannot create, suppress or override an outcome.
"""

from __future__ import annotations

from datetime import date

from .normalize import (
    active_medications,
    flag_against_reference,
    labs_since,
    medications_with_status,
    strength_mg,
)
from .reference_data import (
    ALLERGY_CLASSES,
    DOSE_THRESHOLDS_MG_PER_DAY,
    INTERACTION_PAIRS,
    INTERVAL_DOSES_PER_DAY,
    RULES_VERSION,
)
from .schemas import Chart, RuleOutcome


def _outcome(rule_id: str, outcome: str, summary: str, source_ids: list[str] | None = None) -> RuleOutcome:
    return RuleOutcome(rule_id=rule_id, rule_version=RULES_VERSION, outcome=outcome,  # type: ignore[arg-type]
                       summary=summary, source_ids=source_ids or [])


def allergy_conflict(chart: Chart, today: date) -> RuleOutcome:
    """Compare active medications with recorded allergies via the mapped allergen classes."""
    if chart.sources.get("allergies") and chart.sources["allergies"].status in ("error", "timeout"):
        return _outcome("ALLERGY-1", "unable_to_evaluate", "allergy list could not be retrieved")
    meds = active_medications(chart, today)
    if not chart.allergies:
        return _outcome("ALLERGY-1", "pass", "no allergy records in this chart; absence of a record does not establish that the patient has no allergies")
    hits: list[str] = []
    ids: list[str] = []
    for allergy in chart.allergies:
        title = allergy.title.lower()
        for cls in ALLERGY_CLASSES:
            if str(cls["allergen"]) not in title:
                continue
            for med in meds:
                name = med.drug.lower()
                if any(fragment in name for fragment in cls["drugs"]):  # type: ignore[union-attr]
                    hits.append(f"{med.drug} conflicts with recorded allergy '{allergy.title}' ({cls['class']})")
                    ids += [med.source_id, allergy.source_id]
                elif any(fragment in name for fragment in cls["possible"]):  # type: ignore[union-attr]
                    hits.append(f"{med.drug}: possible cross-reactivity with recorded allergy '{allergy.title}'")
                    ids += [med.source_id, allergy.source_id]
    if hits:
        return _outcome("ALLERGY-1", "flag", "; ".join(hits), sorted(set(ids)))
    return _outcome("ALLERGY-1", "pass", f"no active medication matches a mapped class for {len(chart.allergies)} recorded allergy record(s)",
                    [a.source_id for a in chart.allergies])


def dosage_threshold(chart: Chart, today: date) -> RuleOutcome:
    """Daily dose versus the demo thresholds for the two or three covered medications."""
    findings: list[str] = []
    ids: list[str] = []
    unable: list[str] = []
    for med in active_medications(chart, today):
        name = med.drug.lower()
        drug = next((d for d in DOSE_THRESHOLDS_MG_PER_DAY if d in name), None)
        if drug is None:
            continue
        strength = strength_mg(med.drug)
        try:
            per_dose = float(med.dosage) if med.dosage not in (None, "") else None
        except ValueError:
            per_dose = None
        per_day = INTERVAL_DOSES_PER_DAY.get(str(med.interval)) if med.interval not in (None, "") else None
        if strength is None or per_dose is None or per_day is None:
            unable.append(f"{med.drug}: dose inputs incomplete (strength={strength}, units/dose={per_dose}, frequency={med.interval or 'not recorded'})")
            ids.append(med.source_id)
            continue
        daily = strength * per_dose * per_day
        limit = DOSE_THRESHOLDS_MG_PER_DAY[drug]
        ids.append(med.source_id)
        if daily > limit:
            findings.append(f"{med.drug}: {daily:g} mg/day exceeds the demo threshold of {limit:g} mg/day")
        else:
            findings.append(f"{med.drug}: {daily:g} mg/day within the demo threshold of {limit:g} mg/day")
    if any("exceeds" in f for f in findings):
        return _outcome("DOSE-1", "flag", "; ".join(f for f in findings if "exceeds" in f), ids)
    if unable and not findings:
        return _outcome("DOSE-1", "unable_to_evaluate", "; ".join(unable), ids)
    if findings:
        summary = "; ".join(findings) + (("; " + "; ".join(unable)) if unable else "")
        return _outcome("DOSE-1", "pass", summary, ids)
    return _outcome("DOSE-1", "pass", "no active medication is covered by the demo dose thresholds")


def drug_interaction(chart: Chart, today: date) -> RuleOutcome:
    """Check the reviewed interaction pairs among active medications only."""
    meds = active_medications(chart, today)
    names = [(m, m.drug.lower()) for m in meds]
    hits: list[str] = []
    ids: list[str] = []
    for pair in INTERACTION_PAIRS:
        primaries = [m for m, n in names if str(pair["drug"]) in n]
        if not primaries:
            continue
        for primary in primaries:
            for other, n in names:
                if other.source_id == primary.source_id:
                    continue
                if any(p in n for p in pair["partners"]):  # type: ignore[union-attr]
                    hits.append(f"{pair['id']} {primary.drug} + {other.drug}: recorded classification '{pair['classification']}' ({pair['note']})")
                    ids += [primary.source_id, other.source_id]
    if hits:
        return _outcome("INTERACTION-1", "flag", "; ".join(hits), sorted(set(ids)))
    return _outcome("INTERACTION-1", "pass", f"none of the {len(INTERACTION_PAIRS)} reviewed pairs is present among {len(meds)} active medication(s)",
                    [m.source_id for m in meds])


def laboratory_range(chart: Chart, today: date, days: int) -> RuleOutcome:
    """Preserve value, unit and reference; flag out-of-range against the demo table; no severity."""
    if chart.sources.get("labs") and chart.sources["labs"].status in ("error", "timeout"):
        return _outcome("LAB-1", "unable_to_evaluate", "laboratory results could not be retrieved")
    recent = labs_since(chart, today, days)
    if not recent:
        return _outcome("LAB-1", "pass", f"no laboratory results in the last {days} days")
    out = [flag_against_reference(lab) for lab in recent]
    flagged = [f for f in out if f.outcome == "out_of_range"]
    if flagged:
        summary = "; ".join(f"{f.lab.test}: {f.lab.value} {f.lab.units} ({f.direction}; reference {f.reference})" for f in flagged[:12])
        return _outcome("LAB-1", "flag", summary, [f.lab.source_id for f in flagged])
    evaluated = [f for f in out if f.outcome == "in_range"]
    return _outcome("LAB-1", "pass", f"{len(evaluated)} of {len(recent)} recent results evaluated against the demo reference table; none outside range",
                    [f.lab.source_id for f in evaluated])


def medication_status_rule(chart: Chart, today: date) -> RuleOutcome:
    """Do not present an ended or mismatched order as current (AUDIT D1)."""
    rows = medications_with_status(chart, today)
    uncertain = [(m, e) for m, s, e in rows if s == "ended" and m.active]
    if uncertain:
        return _outcome("MEDSTATUS-1", "flag",
                        "; ".join(f"{m.drug}: {e}" for m, e in uncertain[:10]), [m.source_id for m, _ in uncertain])
    if not rows:
        return _outcome("MEDSTATUS-1", "pass", "no medications recorded")
    return _outcome("MEDSTATUS-1", "pass", f"{len(rows)} medication record(s); status derived from end dates", [m.source_id for m, _, _ in rows])


def run_all(chart: Chart, today: date, recent_lab_days: int = 180) -> list[RuleOutcome]:
    """Run every rule; a crash in one rule becomes an explicit engine_failure outcome, never silence."""
    rules = [
        ("ALLERGY-1", lambda: allergy_conflict(chart, today)),
        ("DOSE-1", lambda: dosage_threshold(chart, today)),
        ("INTERACTION-1", lambda: drug_interaction(chart, today)),
        ("LAB-1", lambda: laboratory_range(chart, today, recent_lab_days)),
        ("MEDSTATUS-1", lambda: medication_status_rule(chart, today)),
    ]
    outcomes: list[RuleOutcome] = []
    for rule_id, fn in rules:
        try:
            outcomes.append(fn())
        except Exception as exc:  # noqa: BLE001 - the contract requires disclosure, not propagation
            outcomes.append(_outcome(rule_id, "engine_failure", f"rule could not be evaluated ({type(exc).__name__})"))
    return outcomes
