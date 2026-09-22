"""Typed, patient-scoped tools the model may call (PRD FR6).

Every tool takes the patient id it wants to read. The tool compares it with the one
patient the session is bound to and returns a `denied` result for anything else, without
revealing whether that patient exists. The model cannot widen the scope (PRD
authorization rules; USER.md REQ-SCOPE-1). Each result is a JSON string with a
`result` of ok / empty / denied / error, and every record carries its `source_id`.

Tools read from the chart the OpenEMR gateway already retrieved for this session; they
never reach the database or the network themselves.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Callable, Literal

from langchain_core.tools import BaseTool, tool

from . import constraints, normalize
from .schemas import Chart


@dataclass
class ChartContext:
    """The one patient this conversation is allowed to see, plus a call log for telemetry."""

    chart: Chart
    today: date
    recent_lab_days: int = 180
    calls: list[str] = field(default_factory=list)
    denials: list[dict[str, Any]] = field(default_factory=list)
    on_call: Callable[[str, dict[str, Any]], None] | None = None
    # Every source_id a tool returned in this turn. A follow-up claim may cite only these:
    # a fact restated from memory without a fresh lookup is not grounded in this turn.
    returned_ids: set[str] = field(default_factory=set)
    # Week 2: the guideline index for this turn (None means the tool reports itself unavailable), and
    # every chunk it returned, keyed by citable id, so the verifier can resolve guideline citations.
    guidelines: Any = None
    evidence: dict[str, dict[str, Any]] = field(default_factory=dict)

    def note(self, payload: Any) -> Any:
        """Record the source_ids in a tool result before it is returned to the model."""
        if isinstance(payload, dict):
            sid = payload.get("source_id")
            if isinstance(sid, str):
                self.returned_ids.add(sid)
            for value in payload.values():
                self.note(value)
        elif isinstance(payload, list):
            for item in payload:
                self.note(item)
        return payload

    @property
    def active_pid(self) -> int:
        return self.chart.patient.pid

    def check(self, tool_name: str, pid: int) -> str | None:
        """Return a denied JSON result when pid is not the active patient; None when allowed."""
        self.calls.append(tool_name)
        if self.on_call:
            self.on_call(tool_name, {"pid_requested_matches_scope": pid == self.active_pid})
        if pid != self.active_pid:
            self.denials.append({"tool": tool_name, "requested_pid": pid})
            return _dump({"result": "denied", "reason": "The requested patient is not the active, authorized patient. "
                                                       "Only the selected patient can be read in this conversation."})
        return None

    def source(self, name: str) -> dict[str, Any]:
        status = self.chart.sources.get(name)
        return status.model_dump() if status else {"status": "ok", "count": 0, "ms": 0}

    def derived_index(self) -> dict[str, dict[str, Any]]:
        """Citable derived facts: rule outcomes ("rule:ALLERGY-1") and compliance signals ("signal:1").

        Each entry names the chart records it was computed from, so a citation of a derived
        fact is still traceable to the record (evals/GROUNDING_RULES.md rule 6).
        """
        index: dict[str, dict[str, Any]] = {}
        for outcome in constraints.run_all(self.chart, self.today, self.recent_lab_days):
            index[f"rule:{outcome.rule_id}"] = {"kind": "rule", **outcome.model_dump()}
        for number, signal in enumerate(normalize.compliance_signals(self.chart, self.today), start=1):
            index[f"signal:{number}"] = {"kind": "signal", "type": signal.kind, "text": signal.text, "source_ids": signal.source_ids}
        return index


def _dump(payload: dict[str, Any], ctx: ChartContext | None = None) -> str:
    if ctx is not None:
        ctx.note(payload)
    return json.dumps(payload, ensure_ascii=False, default=str)


def _result(ctx: ChartContext, source_name: str, records: list[dict[str, Any]], note: str | None = None) -> str:
    status = ctx.source(source_name)
    if status["status"] in ("error", "timeout"):
        return _dump({"result": "error", "source_status": status, "records": [],
                      "note": f"{source_name} could not be retrieved from OpenEMR; do not infer its contents"}, ctx)
    payload: dict[str, Any] = {"result": "ok" if records else "empty", "source_status": status, "records": records, "note": note}
    if not records:
        # An absence is a citable fact: "none recorded" statements cite the empty result itself.
        payload["source_id"] = f"empty:{source_name}"
    return _dump(payload, ctx)


def make_tools(ctx: ChartContext) -> list[BaseTool]:
    """Build the tool set bound to one ChartContext."""

    @tool
    def search_guidelines(query: str) -> str:
        """Short excerpts from public clinical guidance (USPSTF, MedlinePlus) matching the query. Use only when asked what guidance or evidence says. Results are guideline: source_ids for the "evidence" list; never cite them on a claim about the patient."""
        ctx.calls.append("search_guidelines")
        if ctx.on_call:
            ctx.on_call("search_guidelines", {"pid_requested_matches_scope": True})
        if ctx.guidelines is None:
            return _dump({"result": "error", "reason": "guideline search is not available in this deployment", "records": []})
        from .guidelines.retrieve import conditions_from_problems

        conditions = conditions_from_problems([p.title for p in ctx.chart.problems])
        hits = ctx.guidelines.search(query, conditions=conditions)
        records = []
        for hit in hits:
            record = hit.chunk.record()
            ctx.evidence[hit.chunk.source_id] = record
            records.append({"source_id": hit.chunk.source_id, "title": hit.chunk.title, "section": hit.chunk.section,
                            "text": hit.chunk.text, "publisher": hit.chunk.publisher, "published": hit.chunk.published,
                            "url": hit.chunk.url, "score": round(hit.score, 4)})
        note = ("Quote these as evidence, citing their source_ids in the evidence list. They are general guidance, "
                "not statements about this patient, and must not be turned into a recommendation.")
        return _dump({"result": "ok" if records else "empty", "records": records, "note": note,
                      **({} if records else {"source_id": "empty:guidelines"})}, ctx)

    @tool
    def get_patient_context(pid: int) -> str:
        """Identity, appointment and which data sources were retrieved for the active patient. Call this first if unsure what is available."""
        denied = ctx.check("get_patient_context", pid)
        if denied:
            return denied
        chart = ctx.chart
        return _dump({
            "result": "ok",
            "patient": {"source_id": chart.patient.source_id, "pid": chart.patient.pid,
                        "name": normalize.display_name(chart.patient.name), "dob": chart.patient.dob,
                        "age": chart.patient.age, "sex": chart.patient.sex},
            "appointment": chart.appointment.model_dump() if chart.appointment else None,
            "sources": {k: v.model_dump() for k, v in chart.sources.items()},
            "counts": {"problems": len(chart.problems), "medications": len(chart.medications),
                       "allergies": len(chart.allergies), "labs": len(chart.labs),
                       "encounters": len(chart.encounters), "immunizations": len(chart.immunizations)},
        }, ctx)

    @tool
    def get_problems(pid: int, status: Literal["active", "all"] = "active",
                     kind: Literal["disorder", "finding", "situation", "all"] = "disorder") -> str:
        """Problem list entries. kind='disorder' returns diagnoses; 'finding'/'situation' return screening flags and social history; 'all' returns everything."""
        denied = ctx.check("get_problems", pid)
        if denied:
            return denied
        if status == "active":
            rows = normalize.active_problems(ctx.chart, ctx.today, kind=kind)
        else:
            rows = [p for p in ctx.chart.problems if kind == "all" or normalize.problem_kind(p.title) == kind]
        records = [{
            "source_id": p.source_id, "title": normalize.clean_title(p.title), "kind": normalize.problem_kind(p.title),
            "code": p.code, "begdate": p.begdate, "enddate": p.enddate,
            "status": "active" if normalize.is_active_problem(p, ctx.today) else "resolved",
        } for p in rows]
        note = None if records else f"no {status} problems of kind '{kind}' recorded"
        return _result(ctx, "problems", records, note)

    @tool
    def get_medications(pid: int, status: Literal["active", "all"] = "active") -> str:
        """Medications with a status derived from end dates (the record's active flag is unreliable). Returns drug, RxNorm, dose fields and dates."""
        denied = ctx.check("get_medications", pid)
        if denied:
            return denied
        rows = normalize.medications_with_status(ctx.chart, ctx.today)
        records = [{
            "source_id": m.source_id, "drug": m.drug, "rxnorm": m.rxnorm, "status": s, "status_note": e,
            "dosage": m.dosage, "interval": m.interval, "route": m.route,
            "start_date": m.start_date, "end_date": m.end_date, "date_added": m.date_added,
        } for m, s, e in rows if status == "all" or s == "active"]
        note = None if records else f"no {status} medications recorded"
        return _result(ctx, "medications", records, note)

    @tool
    def get_allergies(pid: int) -> str:
        """Recorded allergies and reactions. An empty list means none recorded, which is not the same as no known allergies."""
        denied = ctx.check("get_allergies", pid)
        if denied:
            return denied
        records = [{"source_id": a.source_id, "title": a.title, "reaction": a.reaction, "severity": a.severity,
                    "begdate": a.begdate, "enddate": a.enddate} for a in ctx.chart.allergies]
        note = None if records else "no allergy records; say 'none recorded', never 'no known allergies'"
        return _result(ctx, "allergies", records, note)

    @tool
    def get_labs(pid: int, test: str = "", since_days: int = 365, limit: int = 30) -> str:
        """Laboratory results, newest first. Filter by test name or LOINC substring (e.g. 'potassium', '2823-3'). Each result carries the demo reference range check; the record itself has no ranges."""
        denied = ctx.check("get_labs", pid)
        if denied:
            return denied
        rows = normalize.labs_since(ctx.chart, ctx.today, max(1, since_days))
        needle = (test or "").strip().lower()
        if needle:
            rows = [lab for lab in rows if needle in lab.test.lower() or needle == (lab.code or "").lower()]
        rows = rows[: max(1, min(limit, 200))]
        records = []
        for lab in rows:
            flag = normalize.flag_against_reference(lab)
            records.append({
                "source_id": lab.source_id, "test": lab.test, "code": lab.code, "value": lab.value, "units": lab.units,
                "date": lab.date, "recorded_range": lab.range or None, "recorded_abnormal_flag": lab.abnormal or None,
                "demo_reference": flag.reference, "demo_reference_check": flag.outcome, "direction": flag.direction,
            })
        last = normalize.latest_lab_date(ctx.chart)
        note = None
        if not records:
            note = (f"no matching results in the last {since_days} days; most recent result in the chart is dated {last.isoformat()}"
                    if last else "no laboratory results recorded")
        return _result(ctx, "labs", records, note)

    @tool
    def get_encounters(pid: int, since_days: int = 730, limit: int = 10) -> str:
        """Encounters (visits, admissions) newest first with date, reason, category and class."""
        denied = ctx.check("get_encounters", pid)
        if denied:
            return denied
        rows = normalize.encounters_since(ctx.chart, ctx.today, max(1, since_days))[: max(1, min(limit, 100))]
        records = [{"source_id": e.source_id, "date": e.date, "reason": e.reason, "category": e.category,
                    "class": e.class_code, "facility": e.facility} for e in rows]
        note = None if records else f"no encounters in the last {since_days} days ({len(ctx.chart.encounters)} in the full history)"
        return _result(ctx, "encounters", records, note)

    @tool
    def get_immunizations(pid: int) -> str:
        """Immunization history with dates and CVX codes."""
        denied = ctx.check("get_immunizations", pid)
        if denied:
            return denied
        rows = sorted(ctx.chart.immunizations, key=lambda i: normalize.parse_date(i.date) or date.min, reverse=True)
        records = [{"source_id": i.source_id, "date": i.date, "cvx": i.cvx, "name": i.name} for i in rows]
        return _result(ctx, "immunizations", records, None if records else "no immunizations recorded")

    @tool
    def get_vitals(pid: int) -> str:
        """Recorded vital signs with their dates. Missing measurements are named explicitly; a single reading is not a trend."""
        denied = ctx.check("get_vitals", pid)
        if denied:
            return denied
        records = []
        for v in ctx.chart.vitals:
            fields = {"bps": v.bps, "bpd": v.bpd, "pulse": v.pulse, "height": v.height, "weight": v.weight,
                      "spo2": v.spo2, "bmi": v.bmi, "temperature": v.temperature}
            present = {k: val for k, val in fields.items() if val not in (None, "", "0", "0.00")}
            missing = [k for k in fields if k not in present]
            records.append({"source_id": v.source_id, "date": v.date, **present, "not_recorded": missing})
        return _result(ctx, "vitals", records, None if records else "no vital signs recorded")

    @tool
    def get_compliance_signals(pid: int) -> str:
        """Care-plan adherence signals: open 'review due' items, medications past their end date still flagged active, follow-up gaps, immunization gaps. Each is cited."""
        denied = ctx.check("get_compliance_signals", pid)
        if denied:
            return denied
        signals = normalize.compliance_signals(ctx.chart, ctx.today)
        records = [{"source_id": f"signal:{n}", "kind": s.kind, "text": s.text, "based_on": s.source_ids}
                   for n, s in enumerate(signals, start=1)]
        return _dump({"result": "ok" if records else "empty", "records": records,
                      "note": None if records else "no adherence signals found by the demo rules; this is not a statement that the patient is adherent"}, ctx)

    @tool
    def run_constraint_checks(pid: int) -> str:
        """Deterministic rule engine: allergy conflicts, dose thresholds, interaction pairs, lab ranges, medication status. Report outcomes exactly as returned; never override them."""
        denied = ctx.check("run_constraint_checks", pid)
        if denied:
            return denied
        outcomes = constraints.run_all(ctx.chart, ctx.today, ctx.recent_lab_days)
        return _dump({"result": "ok", "records": [{"source_id": f"rule:{o.rule_id}", **o.model_dump()} for o in outcomes]}, ctx)

    return [get_patient_context, get_problems, get_medications, get_allergies, get_labs,
            get_encounters, get_immunizations, get_vitals, get_compliance_signals, run_constraint_checks, search_guidelines]
