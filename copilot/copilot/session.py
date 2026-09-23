"""Per-user session memory (PRD FR5, conversation-state requirements).

A session is bound to one OpenEMR user and holds the charts the gateway prefetched for
that user's rounding list. Conversation memory exists only for the *active* patient
and is cleared whenever the active patient changes. Sessions expire after an idle
period and can be closed explicitly. Everything lives in process memory: nothing is
written to disk.

Prefetch: when a session opens, a brief is generated in the background (bounded
concurrency) for every patient whose chart has changed since the last one, so
selecting a patient is instant once ready and reopening the panel costs nothing
for charts that stand still. See chart_fingerprint for what counts as a change.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from langchain_core.messages import BaseMessage

from .agent import answer_followup, generate_brief
from .config import Settings
from .schemas import AgentResponse, Chart, ResponseState
from .telemetry import emit, new_correlation_id


def chart_fingerprint(chart: Chart) -> str:
    """Hash of the chart content a brief is derived from.

    Excludes the two fields that differ on every read without changing anything the brief
    could say: the read timestamp, and each source's elapsed time. Everything else counts,
    so a new lab, an ended medication or a source that failed this time all produce a new
    fingerprint and therefore a new brief.
    """
    payload = chart.model_dump(mode="json")
    payload.pop("generated_at", None)
    for source in (payload.get("sources") or {}).values():
        if isinstance(source, dict):
            source.pop("ms", None)
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode()).hexdigest()


@dataclass
class PatientState:
    chart: Chart
    status: str = "queued"            # queued | generating | ready | failed
    fingerprint: str = ""
    brief: AgentResponse | None = None
    error: str | None = None
    history: list[BaseMessage] = field(default_factory=list)
    queued_at: float = field(default_factory=time.perf_counter)
    ready_at: float | None = None


@dataclass
class Session:
    sid: str
    user: dict[str, Any]
    patients: dict[int, PatientState]
    created: datetime
    last_seen: datetime
    active_pid: int | None = None
    opened_at: float = field(default_factory=time.perf_counter)

    def touch(self) -> None:
        self.last_seen = datetime.now(timezone.utc)


def denied(correlation_id: str, pid: int, reason: str) -> AgentResponse:
    """The access-denied response: no patient content, no hint whether the patient exists."""
    return AgentResponse(correlation_id=correlation_id, state=ResponseState.DENIED, state_reason=reason, pid=pid,
                         kind="answer", comparison_window="", generated_at=datetime.now(timezone.utc).isoformat())


class SessionStore:
    def __init__(self, settings: Settings, llm_factory: Callable[[], Any]) -> None:
        self.settings = settings
        self._llm_factory = llm_factory
        self._llm: Any = None
        self.sessions: dict[str, Session] = {}
        self._semaphore = asyncio.Semaphore(settings.prefetch_concurrency)
        # (pid, chart fingerprint, model) -> the brief that was generated from it.
        self._briefs: dict[tuple[int, str, str], AgentResponse] = {}

    # -- model -------------------------------------------------------------
    def llm(self) -> Any:
        if self._llm is None:
            self._llm = self._llm_factory()      # raises ProviderNotApproved: fail closed
        return self._llm

    # -- lifecycle ---------------------------------------------------------
    def open(self, sid: str, user: dict[str, Any], charts: list[Chart], correlation_id: str) -> tuple[Session, list[dict[str, Any]]]:
        """Create (or replace) the session. Charts not assigned to this user are refused (defence in depth)."""
        self.sweep()
        rejected: list[dict[str, Any]] = []
        patients: dict[int, PatientState] = {}
        reused = 0
        for chart in charts:
            if chart.patient.provider_id != int(user["id"]):
                rejected.append({"pid": chart.patient.pid, "reason": "not assigned to this user"})
                emit("scope_rejected_at_open", correlation_id, pid=chart.patient.pid, user_id=user["id"], failure_category="authorization")
                continue
            state = PatientState(chart=chart, fingerprint=chart_fingerprint(chart))
            cached = self._briefs.get(self._brief_key(state))
            if cached is not None:
                # Same patient, same chart content, same model: the brief cannot have changed.
                state.brief, state.status = cached, "ready"
                state.ready_at = time.perf_counter()
                reused += 1
            patients[chart.patient.pid] = state
        now = datetime.now(timezone.utc)
        session = Session(sid=sid, user=user, patients=patients, created=now, last_seen=now)
        self.sessions[sid] = session
        emit("session_opened", correlation_id, session=sid[:8], user_id=user["id"], patients=len(patients),
             rejected=len(rejected), briefs_reused=reused)
        return session, rejected

    async def prefetch(self, sid: str, correlation_id: str) -> None:
        session = self.sessions.get(sid)
        if session is None:
            return
        try:
            llm = self.llm()
        except Exception as exc:  # noqa: BLE001 - provider not approved / not configured
            for state in session.patients.values():
                state.status, state.error = "failed", "model provider not approved or not configured"
            emit("prefetch_failed", correlation_id, session=sid[:8], failure_category="model_provider", error_type=type(exc).__name__)
            return

        async def one(state: PatientState) -> None:
            if state.status == "ready":
                return                      # reused from the cache in open()
            async with self._semaphore:
                if self.sessions.get(sid) is not session:
                    return  # session was closed or replaced while queued
                state.status = "generating"
                cid = new_correlation_id()
                try:
                    state.brief = await asyncio.to_thread(generate_brief, state.chart, llm, self.settings, cid)
                    state.status, state.ready_at = "ready", time.perf_counter()
                    self._remember_brief(state)
                except Exception as exc:  # noqa: BLE001
                    state.status, state.error = "failed", f"brief generation failed ({type(exc).__name__})"
                    emit("brief_failed", cid, pid=state.chart.patient.pid, failure_category="agent", error_type=type(exc).__name__)

        started = time.perf_counter()
        await asyncio.gather(*(one(s) for s in session.patients.values()))
        emit("prefetch_finished", correlation_id, session=sid[:8], patients=len(session.patients),
             ready=sum(1 for s in session.patients.values() if s.status == "ready"),
             duration_ms=int((time.perf_counter() - started) * 1000), budget_s=self.settings.prefetch_budget_s)

    def _brief_key(self, state: PatientState) -> tuple[int, str, str]:
        return (state.chart.patient.pid, state.fingerprint, self.settings.model)

    def _remember_brief(self, state: PatientState) -> None:
        """Keep the brief so the next open of an unchanged chart costs nothing."""
        if state.brief is None or not state.fingerprint:
            return
        self._briefs[self._brief_key(state)] = state.brief
        while len(self._briefs) > max(1, self.settings.brief_cache_size):
            self._briefs.pop(next(iter(self._briefs)))    # oldest insertion first

    def get(self, sid: str) -> Session | None:
        self.sweep()
        session = self.sessions.get(sid)
        if session:
            session.touch()
        return session

    def status(self, sid: str) -> dict[str, Any] | None:
        session = self.get(sid)
        if session is None:
            return None
        return {
            "elapsed_ms": int((time.perf_counter() - session.opened_at) * 1000),
            "active_pid": session.active_pid,
            "patients": [{
                "pid": pid, "status": s.status, "error": s.error,
                "state": s.brief.state.value if s.brief else None,
                "ready_in_ms": int((s.ready_at - s.queued_at) * 1000) if s.ready_at else None,
            } for pid, s in session.patients.items()],
        }

    def select(self, sid: str, pid: int, correlation_id: str) -> tuple[str, AgentResponse | None, str | None]:
        """Make pid the active patient; returns (status, brief, error). Conversation memory for other patients is dropped."""
        session = self.get(sid)
        if session is None:
            return "no_session", None, "session expired"
        state = session.patients.get(pid)
        if state is None:
            emit("scope_denied", correlation_id, session=sid[:8], pid=pid, action="select", failure_category="authorization")
            return "denied", denied(correlation_id, pid, "patient is not on this user's authorized rounding list"), None
        if session.active_pid != pid:
            for other_pid, other in session.patients.items():
                if other_pid != pid:
                    other.history.clear()      # FR5: state cannot cross into another patient
            session.active_pid = pid
            emit("patient_selected", correlation_id, session=sid[:8], pid=pid)
        return state.status, state.brief, state.error

    async def ask_supervised(self, sid: str, pid: int, question: str, documents: list[dict[str, Any]],
                             vision_factory: Callable[[], Any], correlation_id: str) -> dict[str, Any] | None:
        """A follow-up through the graph: the supervisor decides whether the question needs a
        document read first, then hands it to the retriever.

        This is what makes the supervisor's three decisions true of every interaction rather than
        only of the first. It also means a question asked while a document is still unread is
        answered from the chart that document produced, instead of from the chart as it was before
        anyone uploaded anything.
        """
        session = self.get(sid)
        if session is None or pid not in session.patients:
            return None
        self.select(sid, pid, correlation_id)
        state = session.patients[pid]
        summary = await asyncio.to_thread(self.supervisor(vision_factory).start, sid, pid, documents,
                                          correlation_id, question, list(state.history))
        self._absorb_answer(sid, pid, summary)
        return summary

    def _absorb_answer(self, sid: str, pid: int, summary: dict[str, Any]) -> None:
        """Keep the turn the graph produced, so memory works the same through either path."""
        turn = summary.get("turn") or []
        if summary.get("phase") != "done" or not turn:
            return
        state = self.sessions[sid].patients[pid]
        state.history.extend(turn)
        state.history[:] = state.history[-12:]

    async def ask(self, sid: str, pid: int, question: str, correlation_id: str) -> AgentResponse:
        session = self.get(sid)
        if session is None:
            return denied(correlation_id, pid, "session expired; open the co-pilot again")
        state = session.patients.get(pid)
        if state is None or session.active_pid != pid:
            emit("scope_denied", correlation_id, session=sid[:8], pid=pid, action="ask", failure_category="authorization")
            return denied(correlation_id, pid, "patient is not the active, authorized patient")
        try:
            llm = self.llm()
        except Exception as exc:  # noqa: BLE001
            emit("ask_failed", correlation_id, pid=pid, failure_category="model_provider", error_type=type(exc).__name__)
            return AgentResponse(correlation_id=correlation_id, state=ResponseState.UNABLE, pid=pid, kind="answer",
                                 state_reason="model provider not approved or not configured", comparison_window="",
                                 generated_at=state.chart.generated_at)
        try:
            response, turn = await asyncio.wait_for(
                asyncio.to_thread(answer_followup, state.chart, question, list(state.history), llm, self.settings, correlation_id),
                timeout=self.settings.answer_deadline_s)
        except asyncio.TimeoutError:
            emit("ask_timeout", correlation_id, pid=pid, failure_category="deadline", timeout_s=self.settings.answer_deadline_s)
            return AgentResponse(correlation_id=correlation_id, state=ResponseState.UNABLE, pid=pid, kind="answer",
                                 state_reason=f"response deadline of {self.settings.answer_deadline_s:g} s exceeded; retry or review the chart directly",
                                 comparison_window="", generated_at=state.chart.generated_at)
        state.history.extend(turn)
        state.history[:] = state.history[-12:]   # six exchanges of memory is enough for bedside follow-ups
        return response

    # -- Week 2: the supervisor graph ------------------------------------------------------
    def supervisor(self, vision_factory: Callable[[], Any]) -> Any:
        """Built once per store. The graph reads charts and briefs through the store, never directly."""
        if getattr(self, "_supervisor", None) is None:
            from .supervisor import Supervisor

            def chart_provider(sid: str, pid: int) -> Chart:
                session = self.sessions.get(sid)
                if session is None or pid not in session.patients:
                    raise KeyError("no such session or patient")
                return session.patients[pid].chart

            def brief_provider(sid: str, pid: int, chart: Chart) -> AgentResponse | None:
                state = self.sessions[sid].patients[pid]
                fingerprint = chart_fingerprint(chart)
                if state.status == "ready" and state.brief is not None and state.fingerprint == fingerprint:
                    return state.brief
                return self._briefs.get((pid, fingerprint, self.settings.model))

            self._supervisor = Supervisor(self.settings, self.llm, vision_factory, chart_provider, brief_provider)
        return self._supervisor

    def _absorb_supervised(self, sid: str, pid: int, summary: dict[str, Any]) -> None:
        """A finished run's brief becomes the patient's brief, cached like a prefetched one."""
        if summary.get("phase") != "done" or not summary.get("brief"):
            return
        state = self.sessions[sid].patients[pid]
        state.brief = AgentResponse.model_validate(summary["brief"])
        state.status, state.ready_at, state.error = "ready", time.perf_counter(), None
        state.fingerprint = state.fingerprint or chart_fingerprint(state.chart)
        self._remember_brief(state)

    async def supervise(self, sid: str, pid: int, documents: list[dict[str, Any]], vision_factory: Callable[[], Any],
                        correlation_id: str) -> dict[str, Any] | None:
        session = self.get(sid)
        if session is None or pid not in session.patients:
            return None
        # Supervising a patient is opening that patient: the follow-up box on the same page asks
        # about this pid, and ask() answers only for the active one. select() is the single place
        # that switches the active patient and drops every other patient's memory (FR5).
        self.select(sid, pid, correlation_id)
        summary = await asyncio.to_thread(self.supervisor(vision_factory).start, sid, pid, documents, correlation_id)
        self._absorb_supervised(sid, pid, summary)
        return summary

    async def ask_supervised_resume(self, sid: str, pid: int, persisted: list[dict[str, Any]], chart: Chart | None,
                                    vision_factory: Callable[[], Any], correlation_id: str) -> dict[str, Any] | None:
        """The module has persisted what the extractor read; the question is answered from the
        chart as it now stands."""
        summary = await self.supervise_resume(sid, pid, persisted, chart, vision_factory, correlation_id)
        if summary is not None:
            self._absorb_answer(sid, pid, summary)
        return summary

    async def supervise_resume(self, sid: str, pid: int, persisted: list[dict[str, Any]], chart: Chart | None,
                               vision_factory: Callable[[], Any], correlation_id: str) -> dict[str, Any] | None:
        session = self.get(sid)
        if session is None or pid not in session.patients:
            return None
        state = session.patients[pid]
        if chart is not None:
            if chart.patient.pid != pid or chart.patient.provider_id != int(session.user["id"]):
                return {"phase": "denied", "reason": "the re-read chart is not this patient's or not assigned to this user"}
            state.chart = chart                      # the chart as the module re-read it after persisting
            state.fingerprint = chart_fingerprint(chart)
            state.status, state.brief = "generating", None
        summary = await asyncio.to_thread(self.supervisor(vision_factory).resume, sid, pid, persisted, correlation_id)
        self._absorb_supervised(sid, pid, summary)
        return summary

    def close(self, sid: str) -> bool:
        return self.sessions.pop(sid, None) is not None

    def sweep(self) -> int:
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=self.settings.session_idle_minutes)
        stale = [sid for sid, s in self.sessions.items() if s.last_seen < cutoff]
        for sid in stale:
            del self.sessions[sid]
        return len(stale)
