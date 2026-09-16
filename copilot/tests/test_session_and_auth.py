import asyncio
import time
from datetime import datetime, timedelta, timezone

from copilot.llm import ScriptedLLM
from copilot.schemas import AnswerDraft, Claim, ResponseState
from copilot.service.auth import sign, verify
from copilot.session import SessionStore


def user(uid=8):
    return {"id": uid, "username": "doctor1", "name": "Dana Reyes", "groups": ["Physicians"]}


def test_open_rejects_charts_not_assigned_to_the_user(chart101, chart202, settings):
    store = SessionStore(settings, lambda: ScriptedLLM([]))
    session, rejected = store.open("s" * 32, user(8), [chart101, chart202], "cid")
    assert list(session.patients) == [101]
    assert rejected == [{"pid": 202, "reason": "not assigned to this user"}]


def test_select_unknown_patient_is_denied_without_content(chart101, settings):
    store = SessionStore(settings, lambda: ScriptedLLM([]))
    store.open("s" * 32, user(8), [chart101], "cid")
    status, response, _ = store.select("s" * 32, 202, "cid")
    assert status == "denied" and response.state == ResponseState.DENIED
    assert response.sections == [] and response.claims == []


def test_ask_requires_active_patient_and_clears_memory_on_switch(chart101, chart303, settings):
    from langchain_core.messages import AIMessage
    lookup = AIMessage(content="", tool_calls=[{"name": "get_problems", "args": {"pid": 101}, "id": "c1", "type": "tool_call"}])
    final = AnswerDraft(claims=[Claim(text="Essential hypertension is on the problem list.", source_ids=["problem:9001"])])
    store = SessionStore(settings, lambda: ScriptedLLM([lookup, final, lookup, final]))   # each answer needs its own lookup
    store.open("s" * 32, user(8), [chart101, chart303], "cid")

    denied = asyncio.run(store.ask("s" * 32, 101, "hi", "cid"))
    assert denied.state == ResponseState.DENIED          # nothing selected yet

    store.select("s" * 32, 101, "cid")
    ok = asyncio.run(store.ask("s" * 32, 101, "hi", "cid"))
    assert ok.state == ResponseState.COMPLETE and len(store.sessions["s" * 32].patients[101].history) == 2

    store.select("s" * 32, 303, "cid")                    # context change
    assert store.sessions["s" * 32].patients[101].history == []
    assert asyncio.run(store.ask("s" * 32, 101, "hi", "cid")).state == ResponseState.DENIED


def test_sessions_expire(chart101, settings):
    store = SessionStore(settings, lambda: ScriptedLLM([]))
    session, _ = store.open("s" * 32, user(8), [chart101], "cid")
    session.last_seen = datetime.now(timezone.utc) - timedelta(minutes=settings.session_idle_minutes + 1)
    assert store.get("s" * 32) is None


def test_prefetch_marks_failed_when_provider_not_approved(chart101, settings):
    def refuse():
        raise RuntimeError("not approved")

    store = SessionStore(settings, refuse)
    store.open("s" * 32, user(8), [chart101], "cid")
    asyncio.run(store.prefetch("s" * 32, "cid"))
    assert store.status("s" * 32)["patients"][0]["status"] == "failed"


def test_signature_roundtrip_skew_and_mismatch():
    ts = str(int(time.time()))
    body = b'{"pid": 101}'
    sig = sign("secret", ts, "POST", "/session/x/select", body)
    assert verify("secret", ts, sig, "POST", "/session/x/select", body) == (True, "ok")
    assert verify("secret", ts, sig, "POST", "/session/x/select", b'{"pid": 202}')[0] is False
    assert verify("other", ts, sig, "POST", "/session/x/select", body)[0] is False
    old = str(int(time.time()) - 1000)
    assert verify("secret", old, sign("secret", old, "POST", "/p", body), "POST", "/p", body)[1] == "timestamp outside the allowed window"
    assert verify("", ts, sig, "POST", "/p", body)[0] is False
