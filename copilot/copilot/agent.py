"""The agent: an initial rounding brief and a capped follow-up loop.

Both paths end in the same verifier and the same four response states. Nothing the
model writes reaches the UI until the verifier has kept it (PRD D010: no unverified
output is streamed).

Brief:     facts pack (deterministic) -> one structured model call -> verify -> state
Follow-up: tool-calling loop (at most `max_iterations` rounds) -> one structured
           finalisation call -> verify -> state
"""

from __future__ import annotations

import json
import time
from datetime import date
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage

from . import constraints, normalize
from .config import Settings
from .llm import classify_model_error, error_excerpt
from .prompts import BRIEF_SYSTEM, FINALIZE_INSTRUCTION, FOLLOWUP_SYSTEM
from .schemas import AgentResponse, AnswerDraft, BriefDraft, Chart, RemovedClaim, ResponseState, RuleOutcome, VerifiedClaim
from .telemetry import emit, traced
from .tools import ChartContext, make_tools
from .verify import citations_for, verify_brief, verify_claims

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def comparison_window(today: date, hours: int) -> str:
    return f"previous {hours} hours ending {today.isoformat()} (initial brief default; older detail via follow-up questions)"


def verification_index(chart: Chart, ctx: ChartContext) -> dict[str, dict[str, Any]]:
    """Chart records plus derived facts, with the demo reference text attached to labs so cited ranges verify."""
    index = chart.index()
    for lab in chart.labs:
        flag = normalize.flag_against_reference(lab)
        if flag.reference:
            index[lab.source_id]["demo_reference"] = flag.reference
    index.update(ctx.derived_index())
    return index


def allowed_numbers(chart: Chart, today: date, settings: Settings) -> set[str]:
    values = {str(today.year), f"{today.month:g}", f"{today.day:g}", str(settings.comparison_hours),
              str(settings.recent_lab_days), str(chart.patient.pid)}
    if chart.patient.age is not None:
        values.add(str(chart.patient.age))
    return values


def decide_state(chart: Chart, kept: int, removed: list[RemovedClaim], *, model_failed: str | None = None,
                 loop_exhausted: bool = False, rule_outcomes: list[RuleOutcome] | None = None) -> tuple[ResponseState, str]:
    """Map what happened to one of the four states (PRD speed-and-completeness policy)."""
    if model_failed:
        return ResponseState.UNABLE, model_failed
    reasons: list[str] = []
    failed = chart.failed_sources()
    if failed:
        reasons.append(f"source(s) unavailable: {', '.join(failed)}")
    if loop_exhausted:
        reasons.append("tool-call limit reached before the question was fully answered")
    engine_failures = [o.rule_id for o in (rule_outcomes or []) if o.outcome == "engine_failure"]
    if engine_failures:
        reasons.append(f"constraint(s) could not be evaluated: {', '.join(engine_failures)}")
    if removed:
        reasons.append(f"{len(removed)} unverified claim(s) removed")
    if removed and kept == 0:
        return ResponseState.UNABLE, "no claim passed verification; " + "; ".join(reasons)
    if reasons:
        return ResponseState.PARTIAL, "; ".join(reasons)
    return ResponseState.COMPLETE, "all sources for the requested scope were retrieved and every claim was verified"


_ERROR_WORDING = {
    "rate_limit": "the model provider rate-limited the request",
    "provider_unavailable": "the model provider was unavailable or overloaded",
    "other": "the model did not return a valid response",
}


def _describe(exc: BaseException) -> str:
    return f"{_ERROR_WORDING[classify_model_error(exc)]} ({type(exc).__name__})"


def _draft_with_one_retry(fn, correlation_id: str, kind: str):
    """FR12: bounded retry. One retry on a model or schema failure; then give up with a reason."""
    last: BaseException | None = None
    for attempt in (1, 2):
        try:
            return fn(), None
        except Exception as exc:  # noqa: BLE001 - reported as a state, not raised
            last = exc
            emit("model_draft_failed", correlation_id, kind=kind, attempt=attempt,
                 failure_category=classify_model_error(exc), error_type=type(exc).__name__,
                 debug_excerpt=error_excerpt(exc))
    return None, f"{_describe(last)} for the {kind} after 2 attempts" if last else f"no {kind} produced"


# ---------------------------------------------------------------------------
# Initial brief (the five questions from the Agent Design brief)
# ---------------------------------------------------------------------------

def facts_pack(chart: Chart, today: date, settings: Settings) -> dict[str, Any]:
    """Deterministic, compact facts with source ids. This is all the model sees for the brief (PHI3)."""
    primary, basis, extra = normalize.primary_diagnosis_candidate(chart, today)
    disorders = normalize.active_problems(chart, today, kind="disorder")
    flags, _, lab_window = normalize.recent_lab_flags(chart, today, settings.recent_lab_days)
    flags = sorted(flags, key=lambda f: (f.outcome != "out_of_range", f.lab.test))[:20]
    signals = normalize.compliance_signals(chart, today)
    # Every active medication, then the most recent twelve others; the rest are counted, not sent.
    all_meds = normalize.medications_with_status(chart, today)
    meds = [row for row in all_meds if row[1] == "active"] + [row for row in all_meds if row[1] != "active"][:12]
    meds_omitted = len(all_meds) - len(meds)
    outcomes = constraints.run_all(chart, today, settings.recent_lab_days)
    latest_vitals = chart.vitals[0] if chart.vitals else None
    return {
        "patient": {"source_id": chart.patient.source_id, "pid": chart.patient.pid, "name": normalize.display_name(chart.patient.name),
                    "age": chart.patient.age, "sex": chart.patient.sex, "dob": chart.patient.dob},
        "appointment": chart.appointment.model_dump() if chart.appointment else None,
        "comparison_window": comparison_window(today, settings.comparison_hours),
        "sources": {k: v.model_dump() for k, v in chart.sources.items()},
        "primary_diagnosis": None if primary is None else {
            "source_id": primary.source_id, "title": normalize.clean_title(primary.title), "code": primary.code,
            "begdate": primary.begdate, "basis": basis, "also_cite": extra},
        "primary_diagnosis_rule": basis if primary is None else "selected by rule: " + basis,
        "comorbidities": [{"source_id": p.source_id, "title": normalize.clean_title(p.title), "code": p.code, "begdate": p.begdate}
                          for p in disorders if primary is None or p.source_id != primary.source_id][:8],
        "recent_labs": {"window": lab_window, "results": [{
            "source_id": f.lab.source_id, "test": f.lab.test, "value": f.lab.value, "units": f.lab.units, "date": f.lab.date,
            "demo_reference": f.reference, "demo_reference_check": f.outcome, "direction": f.direction} for f in flags]},
        # The first ten signals; large charts can carry dozens of ended-but-flagged-active medications.
        "compliance_signals": [{"source_id": f"signal:{n}", "kind": s.kind, "text": s.text, "based_on": s.source_ids}
                               for n, s in enumerate(signals, start=1)][:10],
        "compliance_signals_omitted": max(0, len(signals) - 10),
        "medications": [{"source_id": m.source_id, "drug": m.drug, "status": s, "status_note": e, "dosage": m.dosage,
                         "interval": m.interval, "route": m.route, "end_date": m.end_date, "date_added": m.date_added}
                        for m, s, e in meds],
        "medications_omitted": meds_omitted,
        "allergies": [{"source_id": a.source_id, "title": a.title, "reaction": a.reaction, "severity": a.severity, "begdate": a.begdate}
                      for a in chart.allergies],
        "rule_outcomes": [{"source_id": f"rule:{o.rule_id}", **o.model_dump()} for o in outcomes],
        "vitals": None if latest_vitals is None else {"source_id": latest_vitals.source_id, "date": latest_vitals.date,
                                                       "pulse": latest_vitals.pulse, "height": latest_vitals.height,
                                                       "not_recorded": [k for k in ("bps", "bpd", "weight", "spo2", "temperature")
                                                                        if getattr(latest_vitals, k) in (None, "", "0", "0.00")]},
    }


def generate_brief(chart: Chart, llm, settings: Settings, correlation_id: str, today: date | None = None) -> AgentResponse:
    today = today or date.today()
    started = time.perf_counter()
    ctx = ChartContext(chart, today, settings.recent_lab_days)
    index = verification_index(chart, ctx)
    facts = facts_pack(chart, today, settings)
    rule_outcomes = constraints.run_all(chart, today, settings.recent_lab_days)

    with traced("rounding_brief", correlation_id, pid=chart.patient.pid, kind="brief") as run:
        messages: list[BaseMessage] = [
            SystemMessage(content=BRIEF_SYSTEM),
            HumanMessage(content="FACTS (JSON):\n" + json.dumps(facts, ensure_ascii=False, default=str) + "\n\nProduce the brief."),
        ]
        draft, failure = _draft_with_one_retry(lambda: llm.structured(messages, BriefDraft), correlation_id, "brief")

        sections, removed = ([], []) if draft is None else verify_brief(draft, index, allowed_numbers(chart, today, settings))
        kept = sum(len(s.claims) for s in sections)
        state, reason = decide_state(chart, kept, removed, model_failed=failure, rule_outcomes=rule_outcomes)
        cited = [sid for s in sections for c in s.claims for sid in c.source_ids]
        response = AgentResponse(
            correlation_id=correlation_id, state=state, state_reason=reason, pid=chart.patient.pid, kind="brief",
            comparison_window=comparison_window(today, settings.comparison_hours), generated_at=chart.generated_at,
            sections=sections, citations=citations_for(cited, index), rule_outcomes=rule_outcomes,
            removed_claims=removed, sources=chart.sources, tool_calls=[], iterations=1 if draft else 0,
            duration_ms=int((time.perf_counter() - started) * 1000), langsmith_run_id=run["run_id"],
        )
    emit("brief_generated", correlation_id, pid=chart.patient.pid, state=state.value, claims_kept=kept,
         claims_removed=len(removed), failed_sources=chart.failed_sources(), duration_ms=response.duration_ms,
         rule_flags=[o.rule_id for o in rule_outcomes if o.outcome == "flag"])
    return response


# ---------------------------------------------------------------------------
# Follow-up questions: the tool loop, capped at settings.max_iterations
# ---------------------------------------------------------------------------

def answer_followup(chart: Chart, question: str, history: list[BaseMessage], llm, settings: Settings,
                    correlation_id: str, today: date | None = None) -> tuple[AgentResponse, list[BaseMessage]]:
    """Answer one question. Returns the response and the two messages to append to memory."""
    today = today or date.today()
    started = time.perf_counter()
    ctx = ChartContext(chart, today, settings.recent_lab_days)
    tools = make_tools(ctx)
    tool_by_name = {t.name: t for t in tools}
    index = verification_index(chart, ctx)

    system = FOLLOWUP_SYSTEM.format(max_iterations=settings.max_iterations, pid=chart.patient.pid,
                                    name=normalize.display_name(chart.patient.name), today=today.isoformat())
    messages: list[BaseMessage] = [SystemMessage(content=system), *history, HumanMessage(content=question)]

    with traced("followup_answer", correlation_id, pid=chart.patient.pid, kind="answer") as run:
        iterations = 0
        loop_exhausted = False
        model_failure: str | None = None
        for _ in range(settings.max_iterations):          # the loop cap the brief asks for
            iterations += 1
            ai = None
            # FR12: one bounded retry of a tool round on malformed model output (for example
            # unparsable tool-call arguments); rate limits are already retried inside the wrapper.
            for attempt in (1, 2):
                try:
                    ai = llm.invoke_with_tools(messages, tools)
                    break
                except Exception as exc:  # noqa: BLE001
                    emit("model_tool_round_failed", correlation_id, iteration=iterations, attempt=attempt,
                         failure_category=classify_model_error(exc), error_type=type(exc).__name__,
                         debug_excerpt=error_excerpt(exc))
                    if attempt == 2:
                        model_failure = f"{_describe(exc)} during tool use"
            if ai is None:
                break
            messages.append(ai)
            if not ai.tool_calls:
                break
            for call in ai.tool_calls:
                tool = tool_by_name.get(call["name"])
                output = tool.invoke(call["args"]) if tool else json.dumps({"result": "error", "reason": "unknown tool"})
                messages.append(ToolMessage(content=str(output), tool_call_id=call["id"]))
        else:
            loop_exhausted = True

        draft: AnswerDraft | None = None
        failure = model_failure
        if failure is None:
            draft, failure = _draft_with_one_retry(
                lambda: llm.structured([*messages, HumanMessage(content=FINALIZE_INSTRUCTION)], AnswerDraft), correlation_id, "answer")

        kept, removed = ([], []) if draft is None else verify_claims(draft.claims, index, allowed_numbers(chart, today, settings))
        state, reason = decide_state(chart, len(kept), removed, model_failed=failure, loop_exhausted=loop_exhausted)
        if (draft is not None and not kept and not removed and (draft.boundary or draft.missing)
                and not loop_exhausted and not chart.failed_sources()):
            # A boundary statement or an honest "not found" is a valid complete answer with no claims,
            # but only when nothing else went wrong on the way.
            state, reason = ResponseState.COMPLETE, "no factual claims; boundary or missing-data statement only"
        cited = [sid for c in kept for sid in c.source_ids]
        response = AgentResponse(
            correlation_id=correlation_id, state=state, state_reason=reason, pid=chart.patient.pid, kind="answer",
            comparison_window=comparison_window(today, settings.comparison_hours), generated_at=chart.generated_at,
            claims=kept, missing=draft.missing if draft else None, boundary=draft.boundary if draft else None,
            citations=citations_for(cited, index), removed_claims=removed, sources=chart.sources,
            tool_calls=ctx.calls, iterations=iterations, duration_ms=int((time.perf_counter() - started) * 1000),
            langsmith_run_id=run["run_id"],
        )

    emit("followup_answered", correlation_id, pid=chart.patient.pid, state=state.value, iterations=iterations,
         loop_exhausted=loop_exhausted, tool_calls=ctx.calls, scope_denials=len(ctx.denials),
         claims_kept=len(kept), claims_removed=len(removed), duration_ms=response.duration_ms)

    # Memory holds only the question and the verified answer text with its citations: no tool
    # payloads, no drafts. Keeping the ids lets a later turn re-cite a verified record legitimately.
    summary = " ".join(f"{c.text} [{', '.join(c.source_ids)}]" for c in kept) \
        or (response.boundary or response.missing or "No verified answer.")
    return response, [HumanMessage(content=question), AIMessage(content=summary)]
