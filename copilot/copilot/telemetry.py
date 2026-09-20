"""PHI-safe operational events and LangSmith tracing (PRD FR14, FR20, NFR6, PHI7).

Two channels, deliberately separate:
- `emit()` writes one JSON line per operational event to the process log. Fields are
  identifiers, states, categories, counts and timings. No names, no record values,
  no prompts, no model text. This is what dashboards and alerts read.
- LangSmith receives the traced run tree (prompts, tool inputs/outputs, model output)
  so a request can be reconstructed. With COPILOT_TRACE_REDACT=1 inputs and outputs
  are hidden and only the tree, timings, metadata and token use are sent.

Every event and every trace carries the correlation_id the OpenEMR module minted.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
import uuid
from collections import Counter
from contextlib import contextmanager
from typing import Any, Iterator

from .config import Settings

_log = logging.getLogger("copilot.events")
if not _log.handlers:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("%(message)s"))
    _log.addHandler(handler)
    _log.setLevel(logging.INFO)
    _log.propagate = False

_FORBIDDEN_KEYS = {"name", "prompt", "response", "text", "claims", "chart", "question", "answer", "dob"}


def new_correlation_id() -> str:
    return str(uuid.uuid4())


_event_counts: Counter[str] = Counter()


def event_counts() -> dict[str, int]:
    """Events emitted since start, by name.

    The retry paths live in the agent, which has no view of the service's counters. They all
    already emit, so the tally is kept here and read by /metrics rather than threading a
    counter through the call stack.
    """
    return dict(_event_counts)


def emit(event: str, correlation_id: str | None = None, **fields: Any) -> dict[str, Any]:
    """Log a structured event. Refuses PHI-shaped keys so a careless caller cannot leak."""
    leak = _FORBIDDEN_KEYS.intersection(fields)
    if leak:
        raise ValueError(f"telemetry event '{event}' carries disallowed field(s): {sorted(leak)}")
    record = {"ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "event": event,
              "correlation_id": correlation_id, **fields}
    _log.info(json.dumps(record, default=str))
    _event_counts[event] += 1
    return record


def configure_tracing(settings: Settings) -> dict[str, Any]:
    """Set LangSmith environment from settings. Returns the redacted configuration evidence."""
    enabled = settings.langsmith_tracing and bool(settings.langsmith_api_key)
    os.environ["LANGSMITH_TRACING"] = "true" if enabled else "false"
    os.environ["LANGSMITH_PROJECT"] = settings.langsmith_project
    if settings.langsmith_api_key:
        os.environ["LANGSMITH_API_KEY"] = settings.langsmith_api_key
    if settings.trace_redact:
        os.environ["LANGSMITH_HIDE_INPUTS"] = "true"
        os.environ["LANGSMITH_HIDE_OUTPUTS"] = "true"
    return {"tracing": enabled, "project": settings.langsmith_project, "redact_inputs_outputs": settings.trace_redact}


@contextmanager
def traced(name: str, correlation_id: str, run_type: str = "chain", **metadata: Any) -> Iterator[dict[str, Any]]:
    """Wrap a unit of work in a LangSmith run (no-op when tracing is off). Yields a dict that receives run_id."""
    info: dict[str, Any] = {"run_id": None}
    if os.environ.get("LANGSMITH_TRACING", "false") != "true":
        yield info
        return
    from langsmith import trace  # local import: optional dependency at runtime

    with trace(name=name, run_type=run_type, metadata={"correlation_id": correlation_id, **metadata},
               tags=["copilot", name]) as run:
        info["run_id"] = str(run.id)
        yield info


def submit_feedback(run_id: str, score: int, category: str) -> bool:
    """FR13: rating + category code only. Free text never goes to external analytics."""
    if os.environ.get("LANGSMITH_TRACING", "false") != "true" or not run_id:
        return False
    from langsmith import Client

    Client().create_feedback(run_id, key="hospitalist-rating", score=score, comment=category)
    return True
