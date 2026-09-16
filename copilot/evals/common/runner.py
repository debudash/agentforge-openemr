"""Executes golden cases and behavioural scenarios against the agent, in process.

Golden case (one turn, one expected answer):
    {"id", "kind": "brief"|"answer", "chart", "question"?, "today"?, "mutations"?, "expect": {...}}

Behavioural scenario (a conversation on one patient; memory carries across turns):
    {"id", "title", "chart", "today"?, "turns": [{"kind", "question"?, "expect": {...}}, ...]}

Every turn's response is checked deterministically (common/checks.py); the judge is optional.
A turn whose agent call died on a provider rate limit is recorded as NOT APPLICABLE, never as
a failure: it says nothing about the agent, only about the endpoint's quota.
"""

from __future__ import annotations

import json
import time
from datetime import date
from pathlib import Path
from typing import Any

from copilot.agent import answer_followup, generate_brief
from copilot.schemas import Chart

from .checks import check, is_rate_limited, snapshot_drift, snapshot_of


def load_chart(fixtures: Path, name: str, mutations: list[dict[str, Any]] | None = None) -> Chart:
    data = json.loads((fixtures / f"{name}.json").read_text(encoding="utf-8"))
    for mutation in mutations or []:
        for group in ("problems", "medications", "allergies", "labs", "encounters", "immunizations", "vitals"):
            for record in data.get(group, []):
                if record["source_id"] == mutation["source_id"]:
                    record.update(mutation["set"])
    return Chart.model_validate(data)


def _judge_turn(judge_fn, judge_llm, chart: Chart, question: str | None, resp: dict[str, Any], today: date) -> tuple[dict[str, Any] | None, str | None, list[str]]:
    """Returns (verdict, na_reason, judge_failures)."""
    if judge_llm is None:
        return None, None, []
    try:
        verdict = judge_fn(judge_llm, json.loads(chart.model_dump_json()), question, resp, today).model_dump()
    except Exception as exc:  # noqa: BLE001
        from copilot.llm import classify_model_error
        category = classify_model_error(exc)
        if category != "other":
            return None, f"judge {category.replace('_', ' ')} ({type(exc).__name__})", []
        return None, f"judge error ({type(exc).__name__})", []
    failed = [k for k in ("faithful",) if verdict.get(k) is False]
    failed += [k for k in ("boundary", "constraint_fidelity", "injection_resisted", "absence_wording") if verdict.get(k) == "no"]
    return verdict, None, [f"judge: {k}" for k in failed]


def run_turn(kind: str, chart: Chart, question: str | None, history: list, llm, settings, cid: str, today: date):
    started = time.perf_counter()
    if kind == "brief":
        response = generate_brief(chart, llm, settings, cid, today)
        new_history = []
    else:
        response, new_history = answer_followup(chart, question or "", list(history), llm, settings, cid, today)
    return response.model_dump(mode="json"), new_history, int((time.perf_counter() - started) * 1000)


def run_golden(case: dict[str, Any], *, fixtures: Path, expected_dir: Path, settings, llm, judge_fn, judge_llm,
               today: date, freeze: bool) -> dict[str, Any]:
    chart = load_chart(fixtures, case["chart"], case.get("mutations"))
    case_today = date.fromisoformat(case["today"]) if case.get("today") else today
    resp, _, elapsed = run_turn(case["kind"], chart, case.get("question"), [], llm, settings, f"golden-{case['id']}", case_today)

    row: dict[str, Any] = {"id": case["id"], "suite": "golden", "state": resp["state"], "state_reason": resp.get("state_reason"), "duration_ms": elapsed,
                           "tool_calls": resp.get("tool_calls"), "iterations": resp.get("iterations"),
                           "claims": len(resp.get("claims", [])) + sum(len(s["claims"]) for s in resp.get("sections", [])),
                           "removed": len(resp.get("removed_claims", [])), "failures": [], "na_reason": None, "judge": None}
    if is_rate_limited(resp):
        row["verdict"] = "na"
        row["na_reason"] = f"agent rate-limited: {resp.get('state_reason')}"
        return row

    failures = check(case["expect"], resp)
    snapshot_path = expected_dir / f"{case['id']}.json"
    actual = snapshot_of(resp)
    if freeze:
        snapshot_path.write_text(json.dumps(actual, indent=2), encoding="utf-8")
        row["snapshot"] = "frozen"
    elif snapshot_path.exists():
        failures += snapshot_drift(json.loads(snapshot_path.read_text(encoding="utf-8")), actual)
        row["snapshot"] = "compared"
    else:
        row["snapshot"] = "none (run with --freeze to record)"

    verdict, na, judge_failures = _judge_turn(judge_fn, judge_llm, chart, case.get("question"), resp, case_today)
    row["judge"] = verdict
    row["judge_na"] = na
    failures += judge_failures
    row["failures"] = failures
    row["verdict"] = "pass" if not failures else "fail"
    row["response_text"] = {"claims": [c["text"] for c in resp.get("claims", [])] + [c["text"] for s in resp.get("sections", []) for c in s["claims"]],
                            "missing": resp.get("missing"), "boundary": resp.get("boundary"),
                            "removed": [r["reason"] for r in resp.get("removed_claims", [])]}
    return row


def run_scenario(scenario: dict[str, Any], *, fixtures: Path, settings, llm, judge_fn, judge_llm, today: date) -> dict[str, Any]:
    chart = load_chart(fixtures, scenario["chart"], scenario.get("mutations"))
    scenario_today = date.fromisoformat(scenario["today"]) if scenario.get("today") else today
    history: list = []
    turns_out: list[dict[str, Any]] = []
    verdict = "pass"
    for number, turn in enumerate(scenario["turns"], start=1):
        resp, new_history, elapsed = run_turn(turn["kind"], chart, turn.get("question"), history, llm, settings,
                                              f"scenario-{scenario['id']}-t{number}", scenario_today)
        history.extend(new_history)
        history[:] = history[-12:]
        out = {"turn": number, "kind": turn["kind"], "question": turn.get("question"), "state": resp["state"], "state_reason": resp.get("state_reason"),
               "tool_calls": resp.get("tool_calls"), "iterations": resp.get("iterations"), "duration_ms": elapsed,
               "claims": [c["text"] for c in resp.get("claims", [])] + [c["text"] for s in resp.get("sections", []) for c in s["claims"]],
               "missing": resp.get("missing"), "boundary": resp.get("boundary"),
               "removed": [r["reason"] for r in resp.get("removed_claims", [])], "failures": [], "na_reason": None, "judge": None}
        if is_rate_limited(resp):
            out["na_reason"] = f"agent rate-limited: {resp.get('state_reason')}"
            turns_out.append(out)
            verdict = "na"
            break  # later turns depend on this one's memory; the scenario cannot be judged
        failures = check(turn.get("expect", {}), resp)
        judge_verdict, na, judge_failures = _judge_turn(judge_fn, judge_llm, chart, turn.get("question"), resp, scenario_today)
        out["judge"], out["judge_na"] = judge_verdict, na
        out["failures"] = failures + judge_failures
        if out["failures"]:
            verdict = "fail"
        turns_out.append(out)
    return {"id": scenario["id"], "suite": "behavioral", "title": scenario.get("title"), "verdict": verdict,
            "turns": turns_out, "failures": [f"turn {t['turn']}: {f}" for t in turns_out for f in t["failures"]],
            "na_reason": next((t["na_reason"] for t in turns_out if t["na_reason"]), None),
            "duration_ms": sum(t["duration_ms"] for t in turns_out),
            "tool_calls": [name for t in turns_out for name in (t["tool_calls"] or [])]}
