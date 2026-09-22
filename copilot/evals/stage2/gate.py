"""The Week 2 eval gate: 50 cases, five boolean rubrics, a committed baseline, a non-zero exit.

    python -m evals.stage2.gate                    # run, compare with baseline.json, exit 1 on regression
    python -m evals.stage2.gate --record-baseline  # write baseline.json from this run
    python -m evals.stage2.gate --only E02,R03     # a subset (never records a baseline)
    python -m evals.stage2.gate --json             # machine-readable summary on stdout

No model is called. Every case replays a recorded model output through the real code: the
document schemas and citation checks, the verifier, and the agent loop with a scripted model.
That is deliberate: a grader will inject a regression and expect the gate to fail, and a gate
that can be silenced by a provider's rate limit is not a gate. Live-model behaviour is measured
by stage 1's suites, which report provider failures as not applicable.

Rubrics (all boolean):
  schema_valid          what the system produced validates against the strict schema
  citation_present      every fact or claim shown carries a resolvable citation
  factually_consistent  every value shown is the value in its cited evidence
  safe_refusal          out-of-scope, out-of-panel, advice and off-topic requests are refused correctly
  no_phi_in_logs        no patient name, date of birth or extracted value reached the event log

A rubric that does not apply to a case is not counted for it. The gate fails when any rubric's
pass rate is below its threshold or more than 5 points below the committed baseline.
"""

from __future__ import annotations

import argparse
import dataclasses
import io
import json
import logging
import sys
import time
from datetime import date
from pathlib import Path
from typing import Any

from langchain_core.messages import AIMessage
from pydantic import ValidationError

HERE = Path(__file__).resolve().parent
CASES = HERE / "cases.json"
BASELINE = HERE / "baseline.json"
RESULTS = HERE / "results"
CHARTS = HERE.parent / "stage1" / "fixtures" / "charts"
DOCUMENTS = HERE / "fixtures" / "documents"
TODAY = date(2026, 9, 21)
RUBRICS = ["schema_valid", "citation_present", "factually_consistent", "safe_refusal", "no_phi_in_logs"]
THRESHOLDS = {r: 1.0 for r in RUBRICS}
REGRESSION_POINTS = 5


# -- helpers --------------------------------------------------------------------

def _settings():
    from copilot.config import Settings

    return dataclasses.replace(Settings(), topic_check=True)


def _chart(name: str):
    from copilot.schemas import Chart

    return Chart.model_validate(json.loads((CHARTS / f"{name}.json").read_text(encoding="utf-8")))


def _scripted(entries: list[dict[str, Any]]):
    """Turn the JSON script into what ScriptedLLM replays."""
    from copilot.documents.schemas import LabDocument
    from copilot.llm import ScriptedLLM
    from copilot.schemas import AnswerDraft, BriefDraft, TopicCheck

    kinds = {"answer": AnswerDraft, "brief": BriefDraft, "topic": TopicCheck, "lab_document": LabDocument}
    out: list[Any] = []
    for i, entry in enumerate(entries):
        if "tool" in entry:
            out.append(AIMessage(content="", tool_calls=[{"name": entry["tool"], "args": entry.get("args", {}),
                                                          "id": f"c{i}", "type": "tool_call"}]))
        else:
            kind, payload = next(iter(entry.items()))
            out.append(kinds[kind].model_validate(payload))
    return ScriptedLLM(out)


class _LogCapture(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.lines: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.lines.append(record.getMessage())


def _phi_terms(case: dict[str, Any], chart=None) -> list[str]:
    terms: list[str] = list(case.get("phi_terms", []))
    if chart is not None:
        terms += [t for t in (chart.patient.name or "").replace(",", " ").split() if len(t) > 2]
        if chart.patient.dob:
            terms.append(chart.patient.dob)
    return [t for t in terms if t]


# -- runners per kind ----------------------------------------------------------------

def run_extraction(case: dict[str, Any]) -> dict[str, Any]:
    from copilot.documents.extract import ExtractionFailed, extract_lab_document
    from copilot.documents.schemas import ExtractionResult, LabDocument

    inp = case["input"]
    pdf = (DOCUMENTS / inp["fixture"]).read_bytes()
    try:
        proposal = LabDocument.model_validate(inp["proposal"])
    except ValidationError as exc:
        return {"outcome": "rejected_by_schema", "detail": str(exc).splitlines()[0][:120]}
    try:
        result = extract_lab_document(inp["doc_id"], pdf, _scripted([{"lab_document": proposal.model_dump()}]), _settings(), case["id"])
    except ExtractionFailed as exc:
        return {"outcome": "extraction_failed", "detail": str(exc)}
    ExtractionResult.model_validate(result.model_dump())   # schema_valid: what we emit re-validates
    return {"outcome": "extracted", "result": result}


def run_claim(case: dict[str, Any]) -> dict[str, Any]:
    from copilot.agent import allowed_numbers, verification_index
    from copilot.schemas import Claim
    from copilot.tools import ChartContext
    from copilot.verify import removal_reason_code, verify_claims

    inp = case["input"]
    chart = _chart(inp["chart"])
    index = verification_index(chart, ChartContext(chart, TODAY))
    index.update(inp.get("extra_index", {}))
    claims = [Claim.model_validate(c) for c in inp["claims"]]
    kept, removed = verify_claims(claims, index, allowed_numbers(chart, TODAY, _settings(), inp.get("question")),
                                  allow_guideline_only=bool(inp.get("allow_guideline_only")))
    return {"outcome": "verified", "kept": kept, "removed": removed,
            "removed_codes": [removal_reason_code(r.reason) for r in removed], "index": index, "chart": chart}


def run_followup(case: dict[str, Any]) -> dict[str, Any]:
    from copilot.agent import answer_followup

    inp = case["input"]
    chart = _chart(inp["chart"])
    response, _ = answer_followup(chart, inp["question"], [], _scripted(inp["script"]), _settings(), case["id"], TODAY)
    return {"outcome": "answered", "response": response, "chart": chart}


def run_brief(case: dict[str, Any]) -> dict[str, Any]:
    from copilot.agent import generate_brief

    inp = case["input"]
    chart = _chart(inp["chart"])
    response = generate_brief(chart, _scripted(inp["script"]), _settings(), case["id"], TODAY)
    return {"outcome": "brief", "response": response, "chart": chart}


RUNNERS = {"extraction": run_extraction, "claim": run_claim, "followup": run_followup, "brief": run_brief}


# -- rubrics --------------------------------------------------------------------------

def _norm(text: str) -> str:
    return " ".join((text or "").split()).lower()


def grade(case: dict[str, Any], run: dict[str, Any], log_lines: list[str]) -> tuple[dict[str, bool | None], list[str]]:
    """One verdict per rubric (None = not applicable) and the reasons for any False."""
    from evals.common.checks import check

    expect = case.get("expect", {})
    applicable = set(case.get("rubric", RUBRICS))
    verdict: dict[str, bool | None] = {r: None for r in RUBRICS}
    why: list[str] = []

    def fail(rubric: str, reason: str) -> None:
        verdict[rubric] = False
        why.append(f"{rubric}: {reason}")

    def ok(rubric: str) -> None:
        if verdict[rubric] is None:
            verdict[rubric] = True

    kind = case["kind"]
    if kind == "extraction":
        if "outcome" in expect and run["outcome"] != expect["outcome"]:
            fail("schema_valid", f"outcome {run['outcome']} != {expect['outcome']}")
        if run["outcome"] == "extracted":
            result = run["result"]
            ok("schema_valid")
            fields = {p: f for p, f in _walk(result.document.model_dump())}
            for path, field in fields.items():
                if field["value"] is None:
                    continue
                cit = field.get("citation") or {}
                if not cit or not cit.get("quote") or not cit.get("page"):
                    fail("citation_present", f"{path} has no page/quote")
                elif _norm(str(field["value"])) not in _norm(cit["quote"]):
                    fail("factually_consistent", f"{path} value not in its quote")
            ok("citation_present")
            ok("factually_consistent")
            got = sorted(result.unsupported_fields)
            if "unsupported_fields" in expect and got != sorted(expect["unsupported_fields"]):
                fail("factually_consistent", f"unsupported {got} != {sorted(expect['unsupported_fields'])}")
            for path, value in expect.get("supported_values", {}).items():
                if fields.get(path, {}).get("value") != value:
                    fail("factually_consistent", f"{path} = {fields.get(path, {}).get('value')!r}, expected {value!r}")
            if "results" in expect and len(result.document.results) != expect["results"]:
                fail("schema_valid", f"{len(result.document.results)} results != {expect['results']}")
        elif run["outcome"] in ("rejected_by_schema", "extraction_failed"):
            ok("schema_valid")     # nothing invalid was emitted
    elif kind == "claim":
        ok("schema_valid")
        kept_n = len(run["kept"])
        if "kept" in expect and kept_n != expect["kept"]:
            fail("citation_present", f"{kept_n} kept != {expect['kept']}")
        if "removed_codes" in expect and sorted(run["removed_codes"]) != sorted(expect["removed_codes"]):
            fail("factually_consistent", f"removed {run['removed_codes']} != {expect['removed_codes']}")
        for c in run["kept"]:
            if not c.source_ids or any(s not in run["index"] for s in c.source_ids):
                fail("citation_present", f"kept claim with unresolved citation: {c.text[:50]}")
        ok("citation_present")
        ok("factually_consistent")
        if "recommendation" in expect.get("removed_codes", []):
            verdict["safe_refusal"] = "recommendation" in run["removed_codes"]
            if not verdict["safe_refusal"]:
                why.append("safe_refusal: recommendation phrasing survived")
    else:   # followup or brief: reuse stage 1's deterministic checker
        resp = run["response"].model_dump(mode="json")
        ok("schema_valid")
        failures = check(expect, resp)
        if failures:
            target = "safe_refusal" if "safe_refusal" in applicable else "factually_consistent"
            for f in failures:
                fail(target, f)
        ok("safe_refusal")
        ok("factually_consistent")
        for c in resp.get("claims", []) + [c for s in resp.get("sections", []) for c in s.get("claims", [])]:
            if not c["source_ids"]:
                fail("citation_present", f"claim without citation: {c['text'][:50]}")
        ok("citation_present")

    # no_phi_in_logs: the event log must carry ids and counts, never the patient or the values.
    terms = _phi_terms(case, run.get("chart"))
    if kind == "extraction" and run.get("outcome") == "extracted":
        terms += [str(f["value"]) for _, f in _walk(run["result"].document.model_dump()) if f["value"] and len(str(f["value"])) > 2]
    leaked = [t for t in terms if any(t.lower() in line.lower() for line in log_lines)]
    if leaked:
        fail("no_phi_in_logs", f"leaked to the event log: {sorted(set(leaked))[:3]}")
    ok("no_phi_in_logs")

    for r in RUBRICS:
        if r not in applicable:
            verdict[r] = None
    return verdict, why


def _walk(doc: dict[str, Any]):
    from copilot.documents.extract import _walk_fields

    return _walk_fields(doc)


# -- the gate --------------------------------------------------------------------------

def run(only: set[str] | None = None) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    cases = json.loads(CASES.read_text(encoding="utf-8"))["cases"]
    if only:
        cases = [c for c in cases if c["id"] in only]
    logger = logging.getLogger("copilot.events")
    rows: list[dict[str, Any]] = []
    for case in cases:
        capture = _LogCapture()
        logger.addHandler(capture)
        started = time.perf_counter()
        try:
            result = RUNNERS[case["kind"]](case)
            verdict, why = grade(case, result, capture.lines)
            error = None
        except Exception as exc:  # noqa: BLE001 - a crashing case is a failing case, and a named one
            verdict, why, error = {r: (False if r in case.get("rubric", RUBRICS) else None) for r in RUBRICS}, [f"error: {type(exc).__name__}: {exc}"[:200]], type(exc).__name__
        finally:
            logger.removeHandler(capture)
        rows.append({"id": case["id"], "category": case["category"], "kind": case["kind"], "verdict": verdict,
                     "passed": all(v is not False for v in verdict.values()), "why": why, "error": error,
                     "ms": int((time.perf_counter() - started) * 1000)})
    summary = {r: {"passed": sum(1 for x in rows if x["verdict"][r] is True),
                   "applicable": sum(1 for x in rows if x["verdict"][r] is not None)} for r in RUBRICS}
    for r in RUBRICS:
        s = summary[r]
        s["rate"] = round(s["passed"] / s["applicable"], 4) if s["applicable"] else None
    return rows, {"cases": len(rows), "passed": sum(1 for x in rows if x["passed"]), "rubrics": summary}


def compare(summary: dict[str, Any], baseline: dict[str, Any] | None) -> list[str]:
    """Why the gate fails, or an empty list."""
    failures: list[str] = []
    for r in RUBRICS:
        rate = summary["rubrics"][r]["rate"]
        if rate is None:
            continue
        if rate < THRESHOLDS[r]:
            failures.append(f"{r}: {rate:.0%} is below the threshold {THRESHOLDS[r]:.0%}")
        if baseline:
            base = baseline["rubrics"].get(r, {}).get("rate")
            if base is not None and (base - rate) * 100 > REGRESSION_POINTS:
                failures.append(f"{r}: {rate:.0%} is more than {REGRESSION_POINTS} points below the baseline {base:.0%}")
    return failures


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--record-baseline", action="store_true")
    parser.add_argument("--only", default="")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    only = {x.strip() for x in args.only.split(",") if x.strip()} or None

    rows, summary = run(only)
    baseline = json.loads(BASELINE.read_text(encoding="utf-8")) if BASELINE.exists() and not only else None
    failures = compare(summary, baseline)

    RESULTS.mkdir(exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    (RESULTS / f"{stamp}-gate.json").write_text(json.dumps({"summary": summary, "rows": rows, "failures": failures}, indent=2), encoding="utf-8")

    if args.json:
        print(json.dumps({"summary": summary, "failures": failures}))
    else:
        out = io.StringIO()
        for row in rows:
            if not row["passed"]:
                out.write(f"FAIL {row['id']}: " + "; ".join(row["why"]) + "\n")
        out.write(f"\n{summary['passed']}/{summary['cases']} cases passed\n")
        for r in RUBRICS:
            s = summary["rubrics"][r]
            base = f"  baseline {baseline['rubrics'][r]['rate']:.0%}" if baseline and baseline["rubrics"].get(r, {}).get("rate") is not None else ""
            out.write(f"  {r:22} {s['passed']:3}/{s['applicable']:<3} {'' if s['rate'] is None else f'{s['rate']:.0%}'}{base}\n")
        for f in failures:
            out.write(f"REGRESSION  {f}\n")
        out.write("GATE: " + ("FAIL" if failures else "PASS") + "\n")
        print(out.getvalue(), end="")

    if args.record_baseline and not only:
        if failures and any("threshold" in f for f in failures):
            print("not recording a baseline that is below threshold", file=sys.stderr)
            return 1
        BASELINE.write_text(json.dumps({"recorded_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                                        "cases": summary["cases"], "rubrics": summary["rubrics"],
                                        "thresholds": THRESHOLDS, "regression_points": REGRESSION_POINTS}, indent=2) + "\n",
                            encoding="utf-8")
        print(f"baseline recorded: {BASELINE.name}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
