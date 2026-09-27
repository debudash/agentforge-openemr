"""The gate must pass on this code and fail when a guard is removed. A gate nobody has seen fail is a guess."""

import json
import logging

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


def test_the_gate_reads_a_non_empty_event_log(baseline):
    """no_phi_in_logs is only worth anything if the log it reads has something in it.

    telemetry configures the copilot.events logger at import time, and used to set its level only
    when the logger had no handlers. The gate attaches its capture handler before the first case
    imports telemetry, so the level stayed at WARNING, every emit() was dropped, and the rubric
    scored 74/74 against an empty log -- in CI and from a fresh clone, though not under pytest,
    where another module imports telemetry first. A vacuous rubric is worse than no rubric.
    """
    logger = logging.getLogger("copilot.events")
    capture = gate._LogCapture()
    logger.addHandler(capture)
    try:
        gate.run(only={"E12"})
    finally:
        logger.removeHandler(capture)
    assert capture.lines, "the gate captured no events: no_phi_in_logs would pass vacuously"


class _LeakIntoTheLog(logging.Filter):
    """Append a patient name and a value to every event, as a careless field would."""

    def filter(self, record: logging.LogRecord) -> bool:
        message = str(record.getMessage())
        record.args = ()
        record.msg = message[:-1] + ', "leaked": "Jane Doe 5.4"}' if message.endswith("}") else message + " Jane Doe 5.4"
        return True


def test_the_gate_fails_when_the_event_log_starts_carrying_values(baseline):
    """The leak goes into the log, not into telemetry.emit.

    Five modules bind `emit` at import time (`from .telemetry import emit`), so patching the
    function reaches whichever callers happened to import after the patch. That made this test
    pass or fail on the order its neighbours ran in -- it passed alone and failed inside its own
    file. The rubric reads the event log, so the log is where the leak belongs: this holds
    whatever imported what.
    """
    logger = logging.getLogger("copilot.events")
    leak = _LeakIntoTheLog()
    logger.addFilter(leak)
    try:
        _, summary = gate.run()
    finally:
        logger.removeFilter(leak)
    failures = gate.compare(summary, baseline)
    assert failures and any(f.startswith("no_phi_in_logs") for f in failures)


def test_an_identifier_that_happens_to_contain_a_value_is_not_a_leak():
    """Every event carries a random langsmith_run_id. About one run in 140 it contained "112", E15's
    extracted value, and no_phi_in_logs failed a docs-only push on 2026-09-27. Ids are not content;
    a value in a content field still is."""
    line = ('{"ts": "2026-09-27T02:48:56Z", "event": "document_extracted", "correlation_id": "E15", '
            '"langsmith_run_id": "01a0e0c6-2be5-7be0-b112-1c6670557683", "duration_ms": 112}')
    assert not any("112" in t for t in gate._log_text(line))
    leaked = line[:-1] + ', "note": "glucose 112"}'
    assert any("112" in t for t in gate._log_text(leaked))
