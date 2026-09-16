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
from .prompts import BRIEF_SYSTEM, FINALIZE_INSTRUCTION, FOLLOWUP_SYSTEM, TOPIC_CHECK_SYSTEM
from .schemas import AgentResponse, AnswerDraft, BriefDraft, Chart, RemovedClaim, ResponseState, RuleOutcome, TopicCheck, VerifiedClaim
from .telemetry import emit, traced
from .tools import ChartContext, make_tools
from .verify import citations_for, verify_brief, verify_claims

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

SCOPE_STATEMENT = ("This co-pilot only answers questions about the selected patient's chart. "
                   "Ask about a specific part of it, for example labs, medications, problems or allergies.")


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
    # Absence records: a source that was read successfully and returned nothing, or a filtered
    # lookup that matched nothing, is citable as "empty:<source>" (see tools._result).
    for name in ("problems", "medications", "allergies", "labs", "encounters", "immunizations", "vitals"):
        status = chart.sources.get(name)
        if status is None or status.status in ("ok", "empty"):
            index[f"empty:{name}"] = {"kind": "empty", "source": name, "status": status.status if status else "ok",
                                      "count_returned": 0, "read_at": chart.generated_at,
                                      "meaning": "the source was read and this lookup returned no records; not a negative finding"}
    return index


def allowed_numbers(chart: Chart, today: date, settings: Settings, question: str | None = None) -> set[str]:
    values = {str(today.year), f"{today.month:g}", f"{today.day:g}", str(settings.comparison_hours),
              str(settings.recent_lab_days), str(chart.patient.pid)}
    if chart.patient.age is not None:
        values.add(str(chart.patient.age))
    if question:
        # Numbers the clinician typed ("in the last 30 days") may be echoed in the answer.
        from .verify import numbers_in
        values |= numbers_in(question)
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

def question_is_about_the_record(question: str, llm, correlation_id: str) -> bool:
    """Classify the question alone, without history. Errors fail open (treated as on-topic)."""
    try:
        verdict = llm.structured([SystemMessage(content=TOPIC_CHECK_SYSTEM), HumanMessage(content=question)], TopicCheck)
    except Exception as exc:  # noqa: BLE001 - the check is an aid, never a blocker
        emit("topic_check_failed", correlation_id, failure_category=classify_model_error(exc), error_type=type(exc).__name__)
        return True
    emit("topic_check", correlation_id, about_patient_record=verdict.about_patient_record)
    return verdict.about_patient_record


def answer_followup(chart: Chart, question: str, history: list[BaseMessage], llm, settings: Settings,
                    correlation_id: str, today: date | None = None) -> tuple[AgentResponse, list[BaseMessage]]:
    """Answer one question. Returns the response and the two messages to append to memory."""
    today = today or date.today()
    started = time.perf_counter()

    # Decide off-topic before the history and the tools are in play (see Settings.topic_check).
    if settings.topic_check and not question_is_about_the_record(question, llm, correlation_id):
        response = AgentResponse(
            correlation_id=correlation_id, state=ResponseState.COMPLETE, state_reason="not a question about this patient's record",
            pid=chart.patient.pid, kind="answer", comparison_window=comparison_window(today, settings.comparison_hours),
            generated_at=chart.generated_at, missing=SCOPE_STATEMENT, off_topic=True, sources=chart.sources,
            duration_ms=int((time.perf_counter() - started) * 1000))
        emit("followup_answered", correlation_id, pid=chart.patient.pid, state="complete", iterations=0, off_topic=True,
             tool_calls=[], scope_denials=0, claims_kept=0, claims_removed=0, duration_ms=response.duration_ms)
        return response, [HumanMessage(content=question), AIMessage(content=SCOPE_STATEMENT)]

    ctx = ChartContext(chart, today, settings.recent_lab_days)
    tools = make_tools(ctx)
    tool_by_name = {t.name: t for t in tools}
    index = verification_index(chart, ctx)

    system = FOLLOWUP_SYSTEM.format(max_iterations=settings.max_iterations, pid=chart.patient.pid,
                                    name=normalize.display_name(chart.patient.name), today=today.isoformat())
    messages: list[BaseMessage] = [SystemMessage(content=system), *history, HumanMessage(content=question)]

    def run_rounds(budget: int, force_first: bool = False) -> tuple[int, bool, str | None]:
        """Tool-calling rounds until the model stops calling tools or the budget is spent.
        `force_first` requires a tool call on the first round. Returns (iterations used,
        loop exhausted, model failure)."""
        used = 0
        for _ in range(budget):                            # the loop cap the brief asks for
            used += 1
            ai = None
            # FR12: one bounded retry of a tool round on malformed model output (for example
            # unparsable tool-call arguments); rate limits are already retried inside the wrapper.
            for attempt in (1, 2):
                try:
                    ai = llm.invoke_with_tools(messages, tools, require_tool=(force_first and used == 1))
                    break
                except Exception as exc:  # noqa: BLE001
                    emit("model_tool_round_failed", correlation_id, iteration=used, attempt=attempt,
                         failure_category=classify_model_error(exc), error_type=type(exc).__name__,
                         debug_excerpt=error_excerpt(exc))
                    if attempt == 2:
                        return used, False, f"{_describe(exc)} during tool use"
            if ai is None:  # pragma: no cover - the retry loop returns or sets ai
                return used, False, "the model did not return a tool round"
            messages.append(ai)
            if not ai.tool_calls:
                return used, False, None
            for call in ai.tool_calls:
                tool = tool_by_name.get(call["name"])
                if tool is None:
                    # An invented tool name. Say which tools exist so the next round can recover,
                    # and keep the attempt visible in the trace.
                    ctx.calls.append(f"unknown:{call['name']}")
                    output = json.dumps({"result": "error", "reason": f"no tool named '{call['name']}'",
                                         "available_tools": sorted(tool_by_name)})
                else:
                    try:
                        output = tool.invoke(call["args"])
                    except Exception as exc:  # noqa: BLE001 - FR6: a tool answers with a structured error, never an exception
                        # Malformed arguments from the model (for example a corrupted pid). Tell it what
                        # was wrong so the next round can correct the call; the trace keeps the attempt.
                        ctx.calls.append(f"invalid-args:{call['name']}")
                        emit("tool_invalid_arguments", correlation_id, tool=call["name"], error_type=type(exc).__name__)
                        output = json.dumps({"result": "error", "reason": f"invalid arguments for {call['name']} ({type(exc).__name__}); "
                                                                        f"pass the active patient's integer pid and valid option values"})
                messages.append(ToolMessage(content=str(output), tool_call_id=call["id"]))
        return used, True, None

    def finalise_and_verify(loop_exhausted: bool, model_failure: str | None):
        draft: AnswerDraft | None = None
        failure = model_failure
        if failure is None:
            draft, failure = _draft_with_one_retry(
                lambda: llm.structured([*messages, HumanMessage(content=FINALIZE_INSTRUCTION)], AnswerDraft), correlation_id, "answer")
        # A follow-up claim may cite only what a tool returned in this turn (plus the derived ids
        # those tools carry). Facts restated from memory without a fresh lookup are removed: the
        # model cannot re-emit an earlier answer to an unrelated question and have it verify.
        off_topic = bool(draft is not None and draft.off_topic)
        if off_topic and draft is not None and draft.claims:
            # The flag wins: an off-topic question carries no chart facts, whatever else the model wrote.
            removed = [RemovedClaim(text=c.text, reason="off-topic question: chart facts discarded") for c in draft.claims]
            kept: list = []
        else:
            kept, removed = ([], []) if draft is None else verify_claims(
                draft.claims, index, allowed_numbers(chart, today, settings, question), turn_ids=ctx.returned_ids)
        return draft, failure, off_topic, kept, removed

    with traced("followup_answer", correlation_id, pid=chart.patient.pid, kind="answer") as run:
        iterations, loop_exhausted, model_failure = run_rounds(settings.max_iterations)
        draft, failure, off_topic, kept, removed = finalise_and_verify(loop_exhausted, model_failure)

        # The model answered from memory (every claim removed, no tool called, not off-topic).
        # One bounded second pass: tell it to look the facts up, then finalise again within the
        # iteration budget that is left (FR12: retry once when policy permits).
        answered_from_memory = bool(removed and not kept and not ctx.calls and not off_topic and failure is None)
        if answered_from_memory and iterations < settings.max_iterations:
            emit("followup_relookup", correlation_id, pid=chart.patient.pid, removed=len(removed))
            messages.append(HumanMessage(content=(
                "Your answer cited records that no tool returned in this turn, so it was rejected. "
                "Use the tools now to retrieve the facts the question needs, then answer again citing only those results.")))
            # The first round of this pass requires a tool call: a model that answered from
            # memory once is not trusted to choose to look things up when merely asked.
            more, loop_exhausted, model_failure = run_rounds(settings.max_iterations - iterations, force_first=True)
            iterations += more
            draft, failure, off_topic, kept, removed = finalise_and_verify(loop_exhausted, model_failure)

        # No lookup, no claims, no boundary: the model never looked at the chart, so whatever it
        # wrote cannot be about this patient. Impose the scope statement rather than trust its
        # wording; keep its text only when it is itself a scope statement about the active patient.
        no_lookup = not ctx.calls and not kept and not removed and failure is None and not loop_exhausted
        if no_lookup and draft is not None and not draft.boundary and not off_topic:
            off_topic = True
            emit("followup_no_lookup_treated_as_off_topic", correlation_id, pid=chart.patient.pid)
        if off_topic and draft is not None:
            # Whichever path set the flag, the doctor sees the fixed scope sentence, not the model's
            # explanation, unless the model itself wrote a scope statement about the active patient.
            own_scope_statement = bool(draft.missing and any(
                marker in draft.missing.lower() for marker in ("active patient", "selected patient", "this patient")))
            if not own_scope_statement:
                draft.missing = SCOPE_STATEMENT

        state, reason = decide_state(chart, len(kept), removed, model_failed=failure, loop_exhausted=loop_exhausted)
        if off_topic and not loop_exhausted and failure is None:
            # Not a question about this patient: nothing was retrieved and nothing failed.
            state, reason = ResponseState.COMPLETE, "not a question about this patient's record"
        elif not kept and removed and not ctx.calls and failure is None:
            reason = "no tool was called in this turn, so nothing supports the answer; ask about a specific part of the chart"
        elif (draft is not None and not kept and not removed and (draft.boundary or draft.missing)
                and not loop_exhausted and not chart.failed_sources()):
            # A boundary statement or an honest "not found" is a valid complete answer with no claims,
            # but only when nothing else went wrong on the way.
            state, reason = ResponseState.COMPLETE, "no chart facts were requested or found; statement only"
        cited = [sid for c in kept for sid in c.source_ids]
        response = AgentResponse(
            correlation_id=correlation_id, state=state, state_reason=reason, pid=chart.patient.pid, kind="answer",
            comparison_window=comparison_window(today, settings.comparison_hours), generated_at=chart.generated_at,
            claims=kept, missing=draft.missing if draft else None, boundary=draft.boundary if draft else None,
            off_topic=off_topic, citations=citations_for(cited, index), removed_claims=removed, sources=chart.sources,
            tool_calls=ctx.calls, iterations=iterations, duration_ms=int((time.perf_counter() - started) * 1000),
            langsmith_run_id=run["run_id"],
        )

    emit("followup_answered", correlation_id, pid=chart.patient.pid, state=state.value, iterations=iterations,
         loop_exhausted=loop_exhausted, off_topic=off_topic, tool_calls=ctx.calls, scope_denials=len(ctx.denials),
         claims_kept=len(kept), claims_removed=len(removed), duration_ms=response.duration_ms)

    # Memory holds only the question and the verified answer text: no tool payloads, no drafts and
    # no citation ids. A later turn that needs one of these facts has to look it up again, which
    # is what keeps "every claim traces to a tool result in this turn" true.
    summary = " ".join(c.text for c in kept) or (response.boundary or response.missing or "No verified answer.")
    return response, [HumanMessage(content=question), AIMessage(content=summary)]
