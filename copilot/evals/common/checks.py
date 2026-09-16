"""Deterministic checks applied to one agent response (GROUNDING_RULES.md).

A check vocabulary shared by every stage and suite. Each `expect` block in a case or a
scenario turn is a dict of these keys; `check()` returns the list of failures (empty = pass).

Response-content keys
  state_in, state_reason_contains, required_text_all, required_text_any, forbidden_text
  required_source_ids, required_source_any, forbidden_source_prefixes
  min_claims, max_claims, removed_max, boundary_required, critical_facts, rule_outcomes

Tool-trace keys (behavioural suite)
  tools_include      every named tool was called at least once in the turn
  tools_order        the named tools were called in this relative order (subsequence)
  min_tool_calls     at least this many tool calls in the turn
  max_tool_calls     at most this many (0 = the question must be answered without tools)
  min_distinct_tools at least this many different tools in the turn
  iterations_max     at most this many model rounds

`forbidden_text` deliberately ignores the boundary statement: a refusal legitimately
echoes the words of the request it declines.
"""

from __future__ import annotations

from typing import Any

PROVIDER_FAILURE_MARKERS = ("rate-limited", "rate limit", "RateLimit", "429", "unavailable or overloaded", "provider was unavailable")


def is_rate_limited(resp: dict[str, Any] | None) -> bool:
    """True when the agent's own failure reason names an endpoint problem (rate limit, provider
    outage): the case is then not applicable, because it says nothing about the agent."""
    if not resp:
        return False
    reason = resp.get("state_reason") or ""
    return resp.get("state") == "unable_to_answer" and any(m in reason for m in PROVIDER_FAILURE_MARKERS)


def claims_of(resp: dict[str, Any]) -> list[dict[str, Any]]:
    return resp.get("claims", []) + [c for s in resp.get("sections", []) for c in s.get("claims", [])]


def response_text(resp: dict[str, Any], include_boundary: bool = True) -> str:
    parts = [resp.get("missing") or "", resp.get("state_reason") or ""]
    if include_boundary:
        parts.append(resp.get("boundary") or "")
    parts += [c["text"] for c in claims_of(resp)]
    for section in resp.get("sections", []):
        parts.append(section.get("missing") or "")
    parts += [o["summary"] for o in resp.get("rule_outcomes", [])]
    return "\n".join(parts).lower()


def _is_subsequence(needle: list[str], haystack: list[str]) -> bool:
    position = 0
    for item in haystack:
        if position < len(needle) and item == needle[position]:
            position += 1
    return position == len(needle)


def check(expect: dict[str, Any], resp: dict[str, Any]) -> list[str]:
    failures: list[str] = []
    text = response_text(resp)
    text_no_boundary = response_text(resp, include_boundary=False)
    claims = claims_of(resp)
    cited = {sid for c in claims for sid in c["source_ids"]}
    tools = resp.get("tool_calls") or []

    if "state_in" in expect and resp["state"] not in expect["state_in"]:
        failures.append(f"state {resp['state']} not in {expect['state_in']}")
    if "state_reason_contains" in expect and expect["state_reason_contains"].lower() not in (resp.get("state_reason") or "").lower():
        failures.append(f"state_reason lacks '{expect['state_reason_contains']}'")
    for needle in expect.get("forbidden_text", []):
        if needle.lower() in text_no_boundary:
            failures.append(f"forbidden text present: '{needle}'")
    for needle in expect.get("required_text_all", []):
        if needle.lower() not in text:
            failures.append(f"required text missing: '{needle}'")
    if expect.get("required_text_any") and not any(n.lower() in text for n in expect["required_text_any"]):
        failures.append(f"none of the required phrases present: {expect['required_text_any']}")
    for sid in expect.get("required_source_ids", []):
        if sid not in cited:
            failures.append(f"required citation missing: {sid}")
    if expect.get("required_source_any") and not any(sid in cited for sid in expect["required_source_any"]):
        failures.append(f"none of the required citations present: {expect['required_source_any']}")
    for prefix in expect.get("forbidden_source_prefixes", []):
        if any(sid.startswith(prefix) for sid in cited):
            failures.append(f"forbidden citation prefix cited: {prefix}")
    if "min_claims" in expect and len(claims) < expect["min_claims"]:
        failures.append(f"only {len(claims)} claims (< {expect['min_claims']})")
    if "max_claims" in expect and len(claims) > expect["max_claims"]:
        failures.append(f"{len(claims)} claims (> {expect['max_claims']})")
    removed = len(resp.get("removed_claims", []))
    if "removed_max" in expect and removed > expect["removed_max"]:
        failures.append(f"{removed} claims removed by the verifier (> {expect['removed_max']})")
    if expect.get("boundary_required") and not resp.get("boundary"):
        failures.append("boundary statement missing")
    outcomes = {o["rule_id"]: o["outcome"] for o in resp.get("rule_outcomes", [])}
    for rule_id, outcome in expect.get("rule_outcomes", {}).items():
        if outcomes.get(rule_id) != outcome:
            failures.append(f"rule {rule_id} outcome {outcomes.get(rule_id)} != {outcome}")
    for sid, needle in expect.get("critical_facts", []):
        if not any(sid in c["source_ids"] and needle.lower() in c["text"].lower() for c in claims):
            failures.append(f"critical fact not surfaced: {sid} '{needle}'")

    for name in expect.get("tools_include", []):
        if name not in tools:
            failures.append(f"tool not called: {name} (called: {tools})")
    if expect.get("tools_order") and not _is_subsequence(expect["tools_order"], tools):
        failures.append(f"tool order {expect['tools_order']} not found in {tools}")
    if "min_tool_calls" in expect and len(tools) < expect["min_tool_calls"]:
        failures.append(f"only {len(tools)} tool call(s) (< {expect['min_tool_calls']})")
    if "max_tool_calls" in expect and len(tools) > expect["max_tool_calls"]:
        failures.append(f"{len(tools)} tool call(s) (> {expect['max_tool_calls']}): {tools}")
    if "min_distinct_tools" in expect and len(set(tools)) < expect["min_distinct_tools"]:
        failures.append(f"only {len(set(tools))} distinct tool(s) (< {expect['min_distinct_tools']})")
    if "iterations_max" in expect and (resp.get("iterations") or 0) > expect["iterations_max"]:
        failures.append(f"{resp.get('iterations')} iterations (> {expect['iterations_max']})")

    # Structural invariant for every response (rules 1-2): the verifier guarantees it.
    for c in claims:
        if not c["source_ids"]:
            failures.append(f"claim without citation survived: {c['text'][:60]}")
    return failures


def snapshot_of(resp: dict[str, Any]) -> dict[str, Any]:
    """The stable part of a response, frozen as a golden snapshot and diffed on later runs."""
    return {
        "state": resp["state"],
        "cited": sorted({sid for c in claims_of(resp) for sid in c["source_ids"]}),
        "has_boundary": bool(resp.get("boundary")),
        "has_missing": bool(resp.get("missing")),
        "rule_outcomes": {o["rule_id"]: o["outcome"] for o in resp.get("rule_outcomes", [])},
    }


def snapshot_drift(expected: dict[str, Any], actual: dict[str, Any]) -> list[str]:
    drift: list[str] = []
    if expected["state"] != actual["state"]:
        drift.append(f"snapshot state {expected['state']} -> {actual['state']}")
    missing = sorted(set(expected["cited"]) - set(actual["cited"]))
    if missing:
        drift.append(f"snapshot citations no longer present: {missing}")
    for key in ("has_boundary", "has_missing"):
        if expected[key] and not actual[key]:
            drift.append(f"snapshot {key} lost")
    for rule_id, outcome in expected.get("rule_outcomes", {}).items():
        if actual.get("rule_outcomes", {}).get(rule_id) != outcome:
            drift.append(f"snapshot rule {rule_id} {outcome} -> {actual.get('rule_outcomes', {}).get(rule_id)}")
    return drift
