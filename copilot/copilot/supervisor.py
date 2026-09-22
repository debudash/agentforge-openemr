"""The Week 2 graph: one supervisor, two workers, explicit logged handoffs (stage 7).

    START -> supervisor -> intake_extractor -> supervisor -(interrupt: module persists)-> supervisor
          -> evidence_retriever -> supervisor -> END

The supervisor holds no tools. It decides three things and nothing else: whether unread documents
need the extractor, when control must go back to the module so what was read can be persisted,
and when the final answer can be assembled. Every edge writes one handoff record with its reason,
so the routing is reconstructible from logs alone.

The agent cannot read OpenEMR documents and must not write to OpenEMR, so the graph pauses after
extraction (LangGraph's interrupt) while the module stores the results and re-reads the chart. The
brief is then generated from the re-read chart, which is what lets rule 3 hold: the "what changed"
claims and everything else cite persisted rows, never the model's extraction output.
"""

from __future__ import annotations

import base64
import time
from datetime import datetime, timezone
from typing import Any, Callable, TypedDict

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from .agent import generate_brief
from .config import Settings
from .documents.extract import ExtractionFailed, extract_document
from .schemas import AgentResponse, Chart, Claim
from .telemetry import emit
from .verify import citations_for, verify_claims

TYPE_LABEL = {"lab_pdf": "Lab report", "intake_form": "Intake form"}


class SupervisorState(TypedDict, total=False):
    sid: str
    pid: int
    correlation_id: str
    documents: list[dict[str, Any]]      # manifest from the module; unread ones carry content_base64
    extractions: list[dict[str, Any]]    # doc_id, doc_type, ok, result | error
    persisted: list[dict[str, Any]]      # what the module wrote: doc_id, source_ids, order_id | sidecar_doc_id, skipped
    brief: dict[str, Any] | None
    changes: list[dict[str, Any]]
    citations: list[dict[str, Any]]
    removed: list[dict[str, Any]]
    handoffs: list[dict[str, Any]]
    phase: str                           # detect | extracted | persisted | done
    started: float


def _handoff(frm: str, to: str, reason: str, started: float, **inputs: Any) -> dict[str, Any]:
    return {"from": frm, "to": to, "reason": reason, "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "duration_ms": int((time.perf_counter() - started) * 1000), "inputs": inputs}


def _unread(state: SupervisorState) -> list[dict[str, Any]]:
    return [d for d in state.get("documents", []) if not d.get("processed") and d.get("content_base64")]


class Supervisor:
    """Builds the graph once. Providers keep it free of session and chart storage concerns."""

    def __init__(self, settings: Settings, llm_factory: Callable[[], Any], vision_llm_factory: Callable[[], Any],
                 chart_provider: Callable[[str, int], Chart],
                 brief_provider: Callable[[str, int, Chart], AgentResponse | None] | None = None) -> None:
        self.settings = settings
        self.llm_factory = llm_factory
        self.vision_llm_factory = vision_llm_factory
        self.chart_provider = chart_provider
        self.brief_provider = brief_provider or (lambda sid, pid, chart: None)
        graph = StateGraph(SupervisorState)
        graph.add_node("supervisor", self.supervisor)
        graph.add_node("intake_extractor", self.intake_extractor)
        graph.add_node("evidence_retriever", self.evidence_retriever)
        graph.add_edge(START, "supervisor")
        graph.add_conditional_edges("supervisor", self.route, {"intake_extractor": "intake_extractor",
                                                               "evidence_retriever": "evidence_retriever", "end": END})
        graph.add_edge("intake_extractor", "supervisor")
        graph.add_edge("evidence_retriever", "supervisor")
        self.graph = graph.compile(checkpointer=MemorySaver())

    # -- nodes ----------------------------------------------------------------------------

    def supervisor(self, state: SupervisorState) -> dict[str, Any]:
        """Decide; never read a chart, call a model or touch a document."""
        started = time.perf_counter()
        cid = state["correlation_id"]
        handoffs = list(state.get("handoffs", []))
        unread = _unread(state)
        extractions = state.get("extractions", [])

        if unread and not extractions:
            handoffs.append(_handoff("supervisor", "intake_extractor", f"{len(unread)} unread document(s)", started,
                                     documents=[{"doc_id": d["doc_id"], "doc_type": d["doc_type"]} for d in unread]))
            emit("supervisor_handoff", cid, pid=state["pid"], to="intake_extractor", documents=len(unread))
            return {"handoffs": handoffs, "phase": "detect"}

        if extractions and state.get("phase") == "extracted" and not state.get("persisted"):
            readable = [e for e in extractions if e.get("ok")]
            if readable:
                # Control goes back to the module: it persists, re-reads the chart, and resumes.
                to_module = _handoff("supervisor", "module", f"{len(readable)} extraction(s) ready to persist", started,
                                     documents=[e["doc_id"] for e in readable])
                emit("supervisor_handoff", cid, pid=state["pid"], to="module", extractions=len(readable))
                # A node that interrupts does not return, so its handoff travels in the interrupt
                # payload for the paused summary and is appended here once the module resumes.
                persisted = interrupt({"phase": "extracted", "extractions": readable, "handoff": to_module})
                handoffs.append(to_module)
                handoffs.append(_handoff("module", "supervisor", "persisted; chart re-read", time.perf_counter(),
                                         documents=[p.get("doc_id") for p in persisted]))
                # The route out of this visit is the retriever; log that edge here, since the node
                # will not be visited again before it.
                handoffs.append(_handoff("supervisor", "evidence_retriever", "documents persisted", time.perf_counter()))
                emit("supervisor_handoff", cid, pid=state["pid"], to="evidence_retriever", reason="documents persisted")
                return {"handoffs": handoffs, "persisted": list(persisted), "phase": "persisted"}
            reason = "nothing readable; brief from the chart as it is"
            handoffs.append(_handoff("supervisor", "evidence_retriever", reason, started))
            emit("supervisor_handoff", cid, pid=state["pid"], to="evidence_retriever", reason=reason)
            return {"handoffs": handoffs, "persisted": [], "phase": "persisted"}

        if state.get("brief") is None:
            reason = "documents persisted" if state.get("persisted") else ("nothing readable; brief from the chart as it is"
                                                                            if extractions else "no unread documents")
            handoffs.append(_handoff("supervisor", "evidence_retriever", reason, started))
            emit("supervisor_handoff", cid, pid=state["pid"], to="evidence_retriever", reason=reason)
            return {"handoffs": handoffs, "phase": state.get("phase") or "detect"}

        changes, citations, removed = self.assemble_changes(state)
        handoffs.append(_handoff("supervisor", "clinician", "final answer assembled", started, changes=len(changes)))
        emit("supervisor_done", cid, pid=state["pid"], changes=len(changes), removed=len(removed), handoffs=len(handoffs) + 0,
             duration_ms=int((time.perf_counter() - state.get("started", started)) * 1000))
        return {"handoffs": handoffs, "changes": changes, "citations": citations, "removed": removed, "phase": "done"}

    def route(self, state: SupervisorState) -> str:
        phase = state.get("phase")
        if phase == "done":
            return "end"
        if _unread(state) and not state.get("extractions"):
            return "intake_extractor"
        if state.get("brief") is None:
            return "evidence_retriever"
        return "end"

    def intake_extractor(self, state: SupervisorState) -> dict[str, Any]:
        """Read every unread document. A failure is recorded, never raised: the brief still happens."""
        started = time.perf_counter()
        cid = state["correlation_id"]
        try:
            vision = self.vision_llm_factory()
        except Exception as exc:  # noqa: BLE001 - provider not approved: every document fails the same way
            vision = None
            vision_error = f"vision model unavailable ({type(exc).__name__})"
        extractions: list[dict[str, Any]] = []
        for doc in _unread(state):
            if vision is None:
                extractions.append({"doc_id": doc["doc_id"], "doc_type": doc["doc_type"], "ok": False, "error": vision_error})
                continue
            try:
                raw = base64.b64decode(doc["content_base64"], validate=True)
                result = extract_document(int(doc["doc_id"]), raw, doc["doc_type"], vision, self.settings, cid, str(doc.get("name", "")))
                extractions.append({"doc_id": doc["doc_id"], "doc_type": doc["doc_type"], "ok": True, "result": result.model_dump()})
            except (ExtractionFailed, ValueError) as exc:
                extractions.append({"doc_id": doc["doc_id"], "doc_type": doc["doc_type"], "ok": False, "error": str(exc)})
        read = sum(1 for e in extractions if e["ok"])
        handoff = _handoff("intake_extractor", "supervisor", f"{read} of {len(extractions)} document(s) read", started,
                           failed=[e["doc_id"] for e in extractions if not e["ok"]])
        return {"extractions": extractions, "phase": "extracted", "handoffs": [*state.get("handoffs", []), handoff]}

    def evidence_retriever(self, state: SupervisorState) -> dict[str, Any]:
        """The Week 1 agent: the brief from the chart as the module has just read it."""
        started = time.perf_counter()
        cid = state["correlation_id"]
        chart = self.chart_provider(state["sid"], state["pid"])
        brief = self.brief_provider(state["sid"], state["pid"], chart)
        reused = brief is not None
        if brief is None:
            brief = generate_brief(chart, self.llm_factory(), self.settings, cid)
        handoff = _handoff("evidence_retriever", "supervisor", f"brief {'reused' if reused else 'generated'}: {brief.state.value}", started,
                           chart_generated_at=chart.generated_at)
        return {"brief": brief.model_dump(mode="json"), "handoffs": [*state.get("handoffs", []), handoff]}

    # -- what changed --------------------------------------------------------------------------

    def assemble_changes(self, state: SupervisorState) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
        """Deterministic sentences about the documents read this run, cited to the documents, then verified."""
        by_id = {int(d["doc_id"]): d for d in state.get("documents", [])}
        persisted = {int(p["doc_id"]): p for p in state.get("persisted", [])}
        index: dict[str, dict[str, Any]] = {}
        claims: list[Claim] = []
        for extraction in state.get("extractions", []):
            doc_id = int(extraction["doc_id"])
            doc = by_id.get(doc_id, {})
            label = TYPE_LABEL.get(extraction["doc_type"], "Document")
            name, date = str(doc.get("name", f"document {doc_id}")), str(doc.get("date", ""))
            sid = f"doc:{doc_id}"
            record: dict[str, Any] = {"kind": "document", "doc_type": extraction["doc_type"], "name": name, "date": date}
            if not extraction.get("ok"):
                record["error"] = extraction.get("error", "")
                text = f"{label} '{name}' ({date}) could not be read; it remains stored for manual review."
            elif doc_id in persisted:
                p = persisted[doc_id]
                if extraction["doc_type"] == "lab_pdf":
                    n = len(p.get("source_ids", []))
                    record["results"] = n
                    text = f"{label} '{name}' ({date}) was read: {n} result(s) added to the chart, pending clinician review."
                else:
                    text = (f"{label} '{name}' ({date}) was read; medications, allergies and family history "
                            f"are reported on intake, not reconciled.")
            else:
                text = f"{label} '{name}' ({date}) was read but not persisted."
            index[sid] = record
            claims.append(Claim(text=text, source_ids=[sid]))
        kept, removed = verify_claims(claims, index)
        citations = citations_for([s for c in kept for s in c.source_ids], index)
        return ([c.model_dump() for c in kept], [c.model_dump(mode="json") for c in citations], [r.model_dump() for r in removed])

    # -- driving the graph ------------------------------------------------------------------------

    @staticmethod
    def _config(sid: str, pid: int) -> dict[str, Any]:
        return {"configurable": {"thread_id": f"{sid}:{pid}"}}

    def start(self, sid: str, pid: int, documents: list[dict[str, Any]], correlation_id: str) -> dict[str, Any]:
        state: SupervisorState = {"sid": sid, "pid": pid, "correlation_id": correlation_id, "documents": documents,
                                  "extractions": [], "persisted": [], "brief": None, "changes": [], "citations": [],
                                  "removed": [], "handoffs": [], "phase": "detect", "started": time.perf_counter()}
        result = self.graph.invoke(state, self._config(sid, pid))
        return self._summary(sid, pid, result)

    def resume(self, sid: str, pid: int, persisted: list[dict[str, Any]], correlation_id: str) -> dict[str, Any]:
        result = self.graph.invoke(Command(resume=persisted), self._config(sid, pid))
        return self._summary(sid, pid, result)

    def _summary(self, sid: str, pid: int, result: dict[str, Any]) -> dict[str, Any]:
        if "__interrupt__" in result:
            values = self.graph.get_state(self._config(sid, pid)).values
            pending = result["__interrupt__"][0].value if result["__interrupt__"] else {}
            handoffs = [*values.get("handoffs", []), *([pending["handoff"]] if isinstance(pending, dict) and pending.get("handoff") else [])]
            return {"phase": "extracted", "extractions": [e for e in values.get("extractions", []) if e.get("ok")],
                    "failed": [e for e in values.get("extractions", []) if not e.get("ok")], "handoffs": handoffs}
        return {"phase": result.get("phase", "done"), "brief": result.get("brief"), "changes": result.get("changes", []),
                "citations": result.get("citations", []), "removed": result.get("removed", []),
                "extractions": [e for e in result.get("extractions", []) if e.get("ok")],
                "failed": [e for e in result.get("extractions", []) if not e.get("ok")], "handoffs": result.get("handoffs", [])}
