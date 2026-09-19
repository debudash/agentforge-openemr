"""Briefs are reused across opens while the chart behind them is unchanged.

The panel used to regenerate every brief on every open, paying for work that could
not have produced a different answer. These cover the two halves of that: an
unchanged chart reuses, and any change to the content a citation could point at
does not.
"""

import asyncio
import dataclasses

from copilot.schemas import AgentResponse, ResponseState
from copilot.session import PatientState, SessionStore, chart_fingerprint


def _store(settings, briefs):
    """A store whose model returns a new brief object on each call, so reuse is visible."""
    calls = {"n": 0}

    def fake_generate(chart, llm, cfg, cid):
        calls["n"] += 1
        return AgentResponse(correlation_id=cid, state=ResponseState.COMPLETE, state_reason="ok",
                             pid=chart.patient.pid, kind="brief", comparison_window="", generated_at=chart.generated_at)

    store = SessionStore(settings, lambda: object())
    briefs.append(calls)
    return store, fake_generate, calls


def _open_and_prefetch(store, chart, user, monkeypatch, fake_generate, sid="s1"):
    monkeypatch.setattr("copilot.session.generate_brief", fake_generate)
    store.open(sid, user, [chart], "cid-open")
    asyncio.run(store.prefetch(sid, "cid-prefetch"))
    return store.sessions[sid]


def test_fingerprint_ignores_read_timestamp_and_timings(chart101):
    """A re-read of the same data must not look like new data."""
    first = chart_fingerprint(chart101)

    reread = chart101.model_copy(deep=True)
    reread.generated_at = "2030-01-01T00:00:00Z"
    for source in reread.sources.values():
        source.ms = source.ms + 977
    assert chart_fingerprint(reread) == first


def test_fingerprint_changes_when_a_citable_record_changes(chart101):
    changed = chart101.model_copy(deep=True)
    changed.labs[0].value = str(float(changed.labs[0].value or 0) + 1)
    assert chart_fingerprint(changed) != chart_fingerprint(chart101)


def test_fingerprint_changes_when_a_source_fails(chart101):
    """A source that errored this time is a different chart, even with the same records."""
    changed = chart101.model_copy(deep=True)
    name = next(iter(changed.sources))
    changed.sources[name].status = "error"
    assert chart_fingerprint(changed) != chart_fingerprint(chart101)


def test_second_open_of_an_unchanged_chart_reuses_the_brief(chart101, settings, monkeypatch):
    store, fake_generate, calls = _store(settings, [])
    user = {"id": chart101.patient.provider_id, "username": "doctor1"}

    _open_and_prefetch(store, chart101, user, monkeypatch, fake_generate)
    assert calls["n"] == 1

    # Reopening: the gateway re-reads the chart, so the timestamp and timings differ.
    reread = chart101.model_copy(deep=True)
    reread.generated_at = "2030-01-01T00:00:00Z"
    session = _open_and_prefetch(store, reread, user, monkeypatch, fake_generate, sid="s2")

    assert calls["n"] == 1, "an unchanged chart must not be briefed again"
    state = session.patients[chart101.patient.pid]
    assert state.status == "ready" and state.brief is not None


def test_changed_chart_is_briefed_again(chart101, settings, monkeypatch):
    store, fake_generate, calls = _store(settings, [])
    user = {"id": chart101.patient.provider_id, "username": "doctor1"}

    _open_and_prefetch(store, chart101, user, monkeypatch, fake_generate)
    assert calls["n"] == 1

    changed = chart101.model_copy(deep=True)
    changed.labs[0].value = str(float(changed.labs[0].value or 0) + 1)
    _open_and_prefetch(store, changed, user, monkeypatch, fake_generate, sid="s3")

    assert calls["n"] == 2, "a changed chart must be briefed again"


def test_cache_is_bounded(chart101, settings, monkeypatch):
    settings = dataclasses.replace(settings, brief_cache_size=2)
    store, fake_generate, _ = _store(settings, [])
    user = {"id": chart101.patient.provider_id, "username": "doctor1"}

    for n in range(5):
        variant = chart101.model_copy(deep=True)
        variant.labs[0].value = str(1000 + n)
        _open_and_prefetch(store, variant, user, monkeypatch, fake_generate, sid=f"s{n}")

    assert len(store._briefs) <= 2
