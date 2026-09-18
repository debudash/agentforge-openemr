"""Run a stage's evaluation suites against the agent.

    python -m evals.run_evals --stage stage1                         # golden + behavioural, live model
    python -m evals.run_evals --stage stage1 --suite golden          # the every-run regression gate
    python -m evals.run_evals --stage stage1 --suite golden --freeze # record golden snapshots (do this on the reference model)
    python -m evals.run_evals --stage stage1 --judge --pace 12         # results upload by default
    python -m evals.run_evals --stage stage1 --no-langsmith            # local only, no upload
    python -m evals.run_evals --stage stage1 --only G1-latest-lab,B3-scope-probe-mid-conversation

Layout: evals/<stage>/{golden/cases.json, golden/expected/, behavioral/scenarios.json, fixtures/charts/,
results/}; evals/common/ holds the runner, checks and judge shared by every stage.

Verdicts per case: pass, fail, or na (not applicable: the model endpoint rate-limited the agent or
the judge, which says nothing about the agent). na is excluded from pass rates and reported apart.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from copilot.config import get_settings  # noqa: E402
from copilot.llm import build_llm  # noqa: E402
from evals.common.judge import judge as judge_fn  # noqa: E402
from evals.common.runner import run_golden, run_scenario  # noqa: E402

EVALS_DIR = Path(__file__).resolve().parent


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stage", default="stage1")
    parser.add_argument("--suite", choices=["golden", "behavioral", "all"], default="all")
    parser.add_argument("--judge", action="store_true", help="add the LLM judge (rules 5, 6, 7, 9)")
    parser.add_argument("--freeze", action="store_true", help="record golden snapshots from this run")
    parser.add_argument("--langsmith", action=argparse.BooleanOptionalAction, default=None,
                        help="upload results to LangSmith (dataset per stage and suite). Defaults to on when LangSmith tracing is configured; --no-langsmith opts out.")
    parser.add_argument("--only", default="", help="comma-separated case or scenario ids")
    parser.add_argument("--pace", type=float, default=float(os.environ.get("EVAL_PACE_S", "0")),
                        help="seconds between cases (free-tier endpoints allow ~20 requests/min)")
    args = parser.parse_args()

    stage_dir = EVALS_DIR / args.stage
    fixtures = stage_dir / "fixtures" / "charts"
    results_dir = stage_dir / "results"
    only = {c.strip() for c in args.only.split(",") if c.strip()}

    settings = get_settings()
    from copilot.telemetry import configure_tracing
    tracing = configure_tracing(settings)
    # Uploads follow tracing unless the operator says otherwise, so a run's results and the
    # model calls behind them land in the same workspace by default.
    if args.langsmith is None:
        args.langsmith = bool(tracing.get("tracing"))
    llm = build_llm(settings)      # raises ProviderNotApproved: evals never run on an unapproved model
    judge_llm = build_llm(settings, settings.judge_model or None) if args.judge else None
    print(f"stage={args.stage} suite={args.suite} agent={settings.model} judge={(settings.judge_model or settings.model) if args.judge else '-'}")

    rows: list[dict[str, Any]] = []

    if args.suite in ("golden", "all"):
        spec = json.loads((stage_dir / "golden" / "cases.json").read_text(encoding="utf-8"))
        today = date.fromisoformat(spec["today"])
        for index, case in enumerate([c for c in spec["cases"] if not only or c["id"] in only]):
            if args.pace and index:
                time.sleep(args.pace)
            try:
                row = run_golden(case, fixtures=fixtures, expected_dir=stage_dir / "golden" / "expected", settings=settings, llm=llm,
                                 judge_fn=judge_fn, judge_llm=judge_llm, today=today, freeze=args.freeze)
            except Exception as exc:  # noqa: BLE001
                row = {"id": case["id"], "suite": "golden", "verdict": "fail", "failures": [f"exception: {type(exc).__name__}: {exc}"], "na_reason": None}
            rows.append(row)
            _print(row)

    if args.suite in ("behavioral", "all") and not args.freeze:
        spec = json.loads((stage_dir / "behavioral" / "scenarios.json").read_text(encoding="utf-8"))
        today = date.fromisoformat(spec["today"])
        for index, scenario in enumerate([s for s in spec["scenarios"] if not only or s["id"] in only]):
            if args.pace and (index or rows):
                time.sleep(args.pace)
            try:
                row = run_scenario(scenario, fixtures=fixtures, settings=settings, llm=llm, judge_fn=judge_fn, judge_llm=judge_llm, today=today)
            except Exception as exc:  # noqa: BLE001
                row = {"id": scenario["id"], "suite": "behavioral", "verdict": "fail", "failures": [f"exception: {type(exc).__name__}: {exc}"], "na_reason": None}
            rows.append(row)
            _print(row)

    summary = _summarise(rows, args, settings)
    results_dir.mkdir(exist_ok=True)
    out = results_dir / f"{datetime.now().strftime('%Y%m%d-%H%M%S')}-{args.suite}.json"
    out.write_text(json.dumps({"summary": summary, "results": rows}, indent=2), encoding="utf-8")
    print(f"\n{summary['pass']} pass, {summary['fail']} fail, {summary['na']} not applicable "
          f"(pass rate over applicable: {summary['pass_rate']}); judge n/a on {summary['judge_na']} -> {out}")
    if args.langsmith:
        try:
            _upload(rows, summary, args, settings)
        except Exception as exc:  # noqa: BLE001 - the results file is already written
            print(f"LangSmith upload failed ({type(exc).__name__}: {exc}); results remain at {out}")
    return 0 if summary["fail"] == 0 else 1


def _print(row: dict[str, Any]) -> None:
    mark = {"pass": "PASS", "fail": "FAIL", "na": "N/A "}[row["verdict"]]
    detail = row.get("na_reason") or "; ".join(row.get("failures", []))
    extra = f" tools={row.get('tool_calls')}" if row.get("tool_calls") else ""
    print(f"{mark} {row['id']:34} {row.get('state', '') or '':16}{extra}  {detail[:160]}")


def _summarise(rows: list[dict[str, Any]], args, settings) -> dict[str, Any]:
    counts = {v: sum(1 for r in rows if r["verdict"] == v) for v in ("pass", "fail", "na")}
    applicable = counts["pass"] + counts["fail"]
    judge_na = sum(1 for r in rows if r.get("judge_na")) + sum(1 for r in rows for t in r.get("turns", []) if t.get("judge_na"))
    claims = sum(r.get("claims", 0) for r in rows if r["suite"] == "golden" and r["verdict"] != "na")
    removed = sum(r.get("removed", 0) for r in rows if r["suite"] == "golden" and r["verdict"] != "na")
    durations = sorted(r["duration_ms"] for r in rows if r.get("duration_ms") and r["verdict"] != "na")
    return {
        "run_at": datetime.now(timezone.utc).isoformat(), "stage": args.stage, "suite": args.suite,
        "agent_model": settings.model, "judge_model": (settings.judge_model or settings.model) if args.judge else None,
        **counts, "pass_rate": round(counts["pass"] / applicable, 4) if applicable else None, "judge_na": judge_na,
        "golden_claim_precision": round(claims / (claims + removed), 4) if (claims + removed) else None,
        "by_suite": {s: {v: sum(1 for r in rows if r["suite"] == s and r["verdict"] == v) for v in ("pass", "fail", "na")} for s in ("golden", "behavioral")},
        "latency_ms": {"p50": durations[len(durations) // 2], "p95": durations[min(len(durations) - 1, int(0.95 * len(durations)))], "n": len(durations)} if durations else {},
    }


def _upload(rows: list[dict[str, Any]], summary: dict[str, Any], args, settings) -> None:
    """One dataset per stage and suite; one run per case with pass/fail/na feedback. No chart content is uploaded."""
    from langsmith import Client

    client = Client()
    project = f"copilot-{args.stage}-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    for row in rows:
        name = f"openemr-copilot-{args.stage}-{row['suite']}"
        dataset = client.read_dataset(dataset_name=name) if client.has_dataset(dataset_name=name) else client.create_dataset(name)
        existing = {e.inputs.get("id") for e in client.list_examples(dataset_id=dataset.id)}
        if row["id"] not in existing:
            client.create_example(inputs={"id": row["id"], "suite": row["suite"]}, outputs={}, dataset_id=dataset.id)
        run = client.create_run(name=row["id"], run_type="chain", project_name=project,
                                inputs={"id": row["id"], "suite": row["suite"]},
                                outputs={"verdict": row["verdict"], "failures": row.get("failures"), "na_reason": row.get("na_reason")},
                                extra={"metadata": {"stage": args.stage, "agent_model": settings.model, "judge_model": summary["judge_model"]}})
        if run is not None and getattr(run, "id", None):
            score = {"pass": 1, "fail": 0}.get(row["verdict"])
            client.create_feedback(run.id, key="verdict", score=score, value=row["verdict"], comment="; ".join(row.get("failures", []))[:500])
    print(f"uploaded {len(rows)} results to LangSmith project {project}")


if __name__ == "__main__":
    raise SystemExit(main())
