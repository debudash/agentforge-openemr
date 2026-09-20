"""The agent service. Private-network only; the OpenEMR module is its single client.

Endpoints (all signed except the two health probes):
  POST /session/open            charts for the user's rounding list -> session; prefetch starts
  GET  /session/{sid}/status    per-patient readiness
  POST /session/{sid}/select    make one patient active; returns its brief when ready
  POST /session/{sid}/ask       follow-up question about the active patient
  POST /session/{sid}/feedback  rating for a response (score + category code only)
  POST /session/{sid}/close
  GET  /healthz                 process is up
  GET  /readyz                  model provider approved, secret configured, tracing state
  GET  /metrics                 counters and latency percentiles, no clinical content
"""

from __future__ import annotations

import asyncio
import statistics
import time
from collections import Counter, defaultdict
from contextlib import asynccontextmanager
from typing import Any

import httpx
from fastapi import Depends, FastAPI, HTTPException, Request, Response
from pydantic import BaseModel, Field

from .. import __version__
from ..config import Settings, get_settings
from ..llm import build_llm
from ..schemas import Chart
from ..session import SessionStore
from ..telemetry import configure_tracing, emit, event_counts, new_correlation_id, submit_feedback
from ..verify import removal_reason_code
from .auth import verify

settings: Settings = get_settings()
store = SessionStore(settings, lambda: build_llm(settings))
tracing_evidence: dict[str, Any] = {}
started_at = time.time()

# -- metrics (no PHI) ---------------------------------------------------------
counters: Counter[str] = Counter()
latencies: dict[str, list[int]] = defaultdict(list)


def record_latency(name: str, ms: int) -> None:
    samples = latencies[name]
    samples.append(ms)
    if len(samples) > 2000:
        del samples[: len(samples) - 2000]


def percentile(samples: list[int], p: float) -> int | None:
    if not samples:
        return None
    ordered = sorted(samples)
    k = max(0, min(len(ordered) - 1, round(p * (len(ordered) - 1))))
    return ordered[k]


# -- app ----------------------------------------------------------------------
@asynccontextmanager
async def lifespan(_: FastAPI):
    tracing_evidence.update(configure_tracing(settings))
    approved, reason = settings.provider_approved()
    emit("service_started", None, version=__version__, model=settings.model, provider_approved=approved,
         provider_reason=reason, tracing=tracing_evidence)
    yield


app = FastAPI(title="Clinical Co-Pilot agent", version=__version__, lifespan=lifespan)


async def signed(request: Request) -> bytes:
    """Dependency: verify the HMAC signature and return the raw body."""
    body = await request.body()
    ok, reason = verify(settings.shared_secret, request.headers.get("x-copilot-timestamp"),
                        request.headers.get("x-copilot-signature"), request.method, request.url.path, body,
                        settings.signature_skew_s)
    if not ok:
        counters["auth_rejected"] += 1
        emit("gateway_auth_rejected", request.headers.get("x-correlation-id"), path=request.url.path, failure_category="authentication", detail=reason)
        raise HTTPException(status_code=401, detail="unauthorized")
    return body


def correlation(request: Request) -> str:
    return request.headers.get("x-correlation-id") or new_correlation_id()


# -- request models ------------------------------------------------------------
class UserRef(BaseModel):
    id: int
    username: str
    name: str = ""
    groups: list[str] = Field(default_factory=list)


class OpenRequest(BaseModel):
    session_id: str = Field(min_length=16, max_length=128)
    user: UserRef
    charts: list[Chart]


class SelectRequest(BaseModel):
    pid: int


class AskRequest(BaseModel):
    pid: int
    question: str = Field(min_length=1, max_length=2000)


class FeedbackRequest(BaseModel):
    run_id: str = ""
    score: int = Field(ge=0, le=1)
    # "citation" is gone on purpose: a claim with a missing or unresolvable citation is
    # deleted by the verifier and can never reach a clinician, so it was not reportable.
    # "mismatch" is the reachable failure -- a real, fresh citation the sentence misreads.
    category: str = Field(pattern=r"^(mismatch|relevance|completeness|other|good)$")


# -- health --------------------------------------------------------------------
@app.get("/health")
@app.get("/healthz")
async def health() -> dict[str, Any]:
    """Liveness: is this process running. Deliberately checks nothing else, so a dependency
    outage never causes the orchestrator to kill a service that is working."""
    return {"status": "ok", "version": __version__, "uptime_s": int(time.time() - started_at)}


async def _reach(url: str, *, timeout: float = 3.0, insecure: bool = False) -> dict[str, Any]:
    """Is this dependency answering? Any HTTP response proves reachability; the status is detail.

    A 5xx is treated as unreachable: the host is there but not serving. No credentials are sent
    and no body is read, so this probe cannot leak anything or cost anything.
    """
    try:
        async with httpx.AsyncClient(timeout=timeout, verify=not insecure, follow_redirects=True) as client:
            result = await client.get(url)
        return {"ok": result.status_code < 500, "detail": f"HTTP {result.status_code}"}
    except Exception as exc:  # noqa: BLE001 - any failure to reach is the answer
        return {"ok": False, "detail": type(exc).__name__}


@app.get("/ready")
@app.get("/readyz")
async def ready(response: Response) -> dict[str, Any]:
    """Readiness: can this service actually do its job right now.

    Two kinds of check. Configuration, which is the PHI1 allowlist control and fails closed before
    any PHI moves; and reachability, which probes the three dependencies a working request needs:
    the model provider, the observability backend, and OpenEMR itself.
    """
    approved, reason = settings.provider_approved()

    openemr_url = settings.openemr_url
    langsmith_url = settings.langsmith_endpoint.rstrip("/") + "/info"
    # The local OpenEMR runs behind a self-signed development certificate. This probe sends no
    # credentials and reads no body, so skipping verification costs nothing.
    probes = await asyncio.gather(
        _reach(settings.endpoint()),
        _reach(langsmith_url) if settings.langsmith_tracing else _noop("tracing disabled"),
        _reach(openemr_url, insecure=True) if openemr_url else _noop("COPILOT_OPENEMR_URL not set", ok=False),
    )
    provider_reach, langsmith_reach, openemr_reach = probes

    checks = {
        "model_provider": {"ok": approved and provider_reach["ok"], "allowlist": reason,
                           "model": settings.model, "endpoint": settings.endpoint(), **provider_reach},
        "shared_secret": {"ok": bool(settings.shared_secret), "detail": "configured" if settings.shared_secret else "missing"},
        "observability": {"ok": langsmith_reach["ok"], "project": settings.langsmith_project,
                          "tracing": settings.langsmith_tracing, **langsmith_reach},
        "openemr": {"ok": openemr_reach["ok"], "url": openemr_url or None, **openemr_reach},
    }
    is_ready = all(check["ok"] for check in checks.values())
    if not is_ready:
        response.status_code = 503
    return {"ready": is_ready, "checks": checks}


async def _noop(detail: str, ok: bool = True) -> dict[str, Any]:
    """A check that is not applicable, reported rather than hidden."""
    return {"ok": ok, "detail": detail}


# -- sessions ------------------------------------------------------------------
@app.post("/session/open")
async def session_open(request: Request, body: bytes = Depends(signed)) -> dict[str, Any]:
    cid = correlation(request)
    payload = OpenRequest.model_validate_json(body)
    approved, reason = settings.provider_approved()
    if not approved:
        counters["open_refused_provider"] += 1
        emit("open_refused", cid, failure_category="model_provider", detail=reason)
        raise HTTPException(status_code=503, detail=f"model provider not approved: {reason}")
    session, rejected = store.open(payload.session_id, payload.user.model_dump(), payload.charts, cid)
    asyncio.create_task(store.prefetch(payload.session_id, cid))
    counters["sessions_opened"] += 1
    return {"session_id": session.sid, "correlation_id": cid,
            "patients": [{"pid": pid, "status": s.status} for pid, s in session.patients.items()],
            "rejected": rejected, "prefetch_budget_s": settings.prefetch_budget_s,
            "disclaimer": settings.demo_disclaimer}


@app.get("/session/{sid}/status")
async def session_status(sid: str, request: Request, _: bytes = Depends(signed)) -> dict[str, Any]:
    status = store.status(sid)
    if status is None:
        raise HTTPException(status_code=404, detail="no such session")
    return status


@app.post("/session/{sid}/select")
async def session_select(sid: str, request: Request, body: bytes = Depends(signed)) -> dict[str, Any]:
    cid = correlation(request)
    payload = SelectRequest.model_validate_json(body)
    status, brief, error = store.select(sid, payload.pid, cid)
    if status == "no_session":
        raise HTTPException(status_code=404, detail="no such session")
    counters[f"select_{status}"] += 1
    if brief is not None:
        counters[f"brief_state_{brief.state.value}"] += 1
        # Kept alongside claims_removed so the verified-claim rate can be read straight off
        # /metrics. Counting only removals tells you a denominator is missing, not what it is.
        counters["claims_kept"] += sum(len(section.claims) for section in brief.sections)
        counters["claims_removed"] += len(brief.removed_claims)
        for claim in brief.removed_claims:
            counters[f"removed_{removal_reason_code(claim.reason)}"] += 1
        record_latency("brief_ms", brief.duration_ms)
    return {"status": status, "correlation_id": cid, "error": error,
            "brief": brief.model_dump(mode="json") if brief else None}


@app.post("/session/{sid}/ask")
async def session_ask(sid: str, request: Request, body: bytes = Depends(signed)) -> dict[str, Any]:
    cid = correlation(request)
    payload = AskRequest.model_validate_json(body)
    response = await store.ask(sid, payload.pid, payload.question, cid)
    counters[f"answer_state_{response.state.value}"] += 1
    counters["tool_calls"] += len(response.tool_calls)
    counters["claims_kept"] += len(response.claims)
    counters["claims_removed"] += len(response.removed_claims)
    # Why a claim died is the most diagnostic signal this design produces: "cites another patient"
    # and "restated without a lookup" call for completely different responses.
    for claim in response.removed_claims:
        counters[f"removed_{removal_reason_code(claim.reason)}"] += 1
    record_latency("answer_ms", response.duration_ms)
    return response.model_dump(mode="json")


@app.post("/session/{sid}/feedback")
async def session_feedback(sid: str, request: Request, body: bytes = Depends(signed)) -> dict[str, Any]:
    cid = correlation(request)
    payload = FeedbackRequest.model_validate_json(body)
    if store.get(sid) is None:
        raise HTTPException(status_code=404, detail="no such session")
    submitted = False
    try:
        submitted = submit_feedback(payload.run_id, payload.score, payload.category)
    except Exception as exc:  # noqa: BLE001 - feedback must never break the clinical flow
        emit("feedback_failed", cid, failure_category="observability", error_type=type(exc).__name__)
    counters[f"feedback_{payload.category}"] += 1
    emit("feedback_received", cid, score=payload.score, category=payload.category, submitted=submitted)
    return {"submitted": submitted}


@app.post("/session/{sid}/close")
async def session_close(sid: str, request: Request, _: bytes = Depends(signed)) -> dict[str, Any]:
    closed = store.close(sid)
    emit("session_closed", correlation(request), session=sid[:8], existed=closed)
    return {"closed": closed}


@app.get("/metrics")
async def metrics(request: Request, _: bytes = Depends(signed)) -> dict[str, Any]:
    events = event_counts()
    return {
        "counters": dict(counters),
        "latency_ms": {name: {"p50": percentile(s, 0.5), "p95": percentile(s, 0.95), "p99": percentile(s, 0.99),
                              "n": len(s), "mean": int(statistics.fmean(s)) if s else None}
                       for name, s in latencies.items()},
        "sessions_active": len(store.sessions),
        # The retry paths live in the agent and all emit; telemetry keeps the tally so /metrics
        # can report them without threading a counter through the call stack.
        "retries": {
            "rate_limited": events.get("model_rate_limited", 0),
            "draft_failed": events.get("model_draft_failed", 0),
            "tool_round_failed": events.get("model_tool_round_failed", 0),
            "forced_relookup": events.get("followup_relookup", 0),
            "topic_check_failed": events.get("topic_check_failed", 0),
        },
    }
