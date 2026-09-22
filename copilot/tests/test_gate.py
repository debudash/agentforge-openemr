"""The gate must pass on this code and fail when a guard is removed. A gate nobody has seen fail is a guess."""

import json

import pytest

from evals.stage2 import gate


@pytest.fixture(scope="module")
def baseline():
    return json.loads(gate.BASELINE.read_text(encoding="utf-8")) if gate.BASELINE.exists() else None


def test_the_gate_passes_on_the_current_code(baseline):
    rows, summary = gate.run()
    failing = [r["id"] + ": " + "; ".join(r["why"]) for r in rows if not r["passed"]]
    assert not failing, failing
    assert summary["cases"] >= 50
    assert gate.compare(summary, baseline) == []


def test_the_gate_fails_when_the_verifier_stops_checking_citations(monkeypatch, baseline):
    import copilot.verify as verify

    monkeypatch.setattr(verify, "check_claim", lambda *a, **k: None)   # every claim survives
    _, summary = gate.run()
    failures = gate.compare(summary, baseline)
    assert failures and any(f.startswith("citation_present") or f.startswith("factually_consistent") for f in failures)


def test_the_gate_fails_when_extraction_stops_demoting_invented_citations(monkeypatch, baseline):
    import copilot.documents.extract as extract

    monkeypatch.setattr(extract, "demote_uncited", lambda doc, *a, **k: (doc, []))
    _, summary = gate.run()
    failures = gate.compare(summary, baseline)
    assert failures and any(f.startswith("factually_consistent") for f in failures)


def test_the_gate_fails_when_the_boundary_regex_is_weakened(monkeypatch, baseline):
    import re

    import copilot.verify as verify

    monkeypatch.setattr(verify, "_RECOMMENDATION", re.compile(r"(?!x)x"))   # matches nothing
    _, summary = gate.run()
    failures = gate.compare(summary, baseline)
    assert failures and any(f.startswith("safe_refusal") for f in failures)


def test_the_gate_fails_when_the_event_log_starts_carrying_values(monkeypatch, baseline):
    import copilot.telemetry as telemetry

    original = telemetry.emit

    def leaky(event, correlation_id=None, **fields):
        return original(event, correlation_id, leaked="Jane Doe 5.4", **fields)

    monkeypatch.setattr(telemetry, "emit", leaky)
    monkeypatch.setattr("copilot.documents.extract.emit", leaky)
    _, summary = gate.run()
    failures = gate.compare(summary, baseline)
    assert failures and any(f.startswith("no_phi_in_logs") for f in failures)
