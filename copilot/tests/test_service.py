"""End-to-end through the HTTP gateway with a scripted model."""

import json
import time

from fastapi.testclient import TestClient

from copilot.llm import ScriptedLLM
from copilot.schemas import AnswerDraft, BriefDraft, BriefSection, Claim
from copilot.service import app as service
from copilot.service.auth import sign

SECRET = service.settings.shared_secret


def signed(client, method, path, payload=None):
    body = json.dumps(payload).encode() if payload is not None else b""
    ts = str(int(time.time()))
    headers = {"X-Copilot-Timestamp": ts, "X-Copilot-Signature": sign(SECRET, ts, method, path, body),
               "Content-Type": "application/json", "X-Correlation-Id": "cid-http"}
    return client.request(method, path, content=body, headers=headers)


def test_unsigned_requests_are_rejected():
    with TestClient(service.app) as client:
        assert client.post("/session/open", content=b"{}").status_code == 401
        assert client.get("/session/abc/status").status_code == 401
        assert client.get("/healthz").status_code == 200


def test_full_flow_open_status_select_ask(chart101, monkeypatch):
    brief = BriefDraft(sections=[BriefSection(key="allergies", title="Allergies",
                                              claims=[Claim(text="Penicillin V allergy with rash recorded.", source_ids=["allergy:8001"])])])
    answer = AnswerDraft(claims=[Claim(text="Lisinopril 10 MG Oral Tablet is active.", source_ids=["prescription:7001"])])
    from langchain_core.messages import AIMessage
    lookup = AIMessage(content="", tool_calls=[{"name": "get_medications", "args": {"pid": 101}, "id": "c1", "type": "tool_call"}])
    service.store._llm = ScriptedLLM([brief, lookup, answer])   # a claim must be backed by a lookup in its own turn

    with TestClient(service.app) as client:
        opened = signed(client, "POST", "/session/open", {
            "session_id": "abcdefghijklmnopqrstuvwxyz123456",
            "user": {"id": 8, "username": "doctor1", "name": "Dana Reyes", "groups": ["Physicians"]},
            "charts": [json.loads(chart101.model_dump_json())],
        })
        assert opened.status_code == 200, opened.text
        sid = opened.json()["session_id"]

        deadline = time.time() + 10
        while time.time() < deadline:
            status = signed(client, "GET", f"/session/{sid}/status").json()
            if status["patients"][0]["status"] == "ready":
                break
            time.sleep(0.05)
        assert status["patients"][0]["status"] == "ready", status

        selected = signed(client, "POST", f"/session/{sid}/select", {"pid": 101}).json()
        assert selected["status"] == "ready" and selected["brief"]["state"] == "complete"

        asked = signed(client, "POST", f"/session/{sid}/ask", {"pid": 101, "question": "Current meds?"}).json()
        assert asked["state"] == "complete" and asked["claims"][0]["source_ids"] == ["prescription:7001"]

        other = signed(client, "POST", f"/session/{sid}/ask", {"pid": 202, "question": "Current meds?"}).json()
        assert other["state"] == "access_denied" and other["claims"] == []

        metrics = signed(client, "GET", "/metrics").json()
        assert metrics["counters"]["answer_state_access_denied"] >= 1
        assert signed(client, "POST", f"/session/{sid}/close").json()["closed"] is True
