"""Shared fixtures: OAuth client, tokens, API sessions, and a DB helper.

Targets the local docker/development-easy stack. The dev stack uses a
self-signed certificate, so TLS verification is off (local only).
"""

import sys
from pathlib import Path

import pytest
import requests

# Configuration and database access live in scripts/oe_api.py so the setup scripts and the
# Railway cron container can share them without depending on pytest. They are re-exported
# here, so `from conftest import db_query` (and the rest) keeps working across the suite.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from oe_api import (  # noqa: E402,F401
    BASE_URL,
    COMPOSE_DIR,
    DB_VIA,
    FHIR,
    OAUTH,
    OE_PASS,
    OE_USER,
    READ_SCOPES,
    REST,
    _safe_id,
    db_query,
)


@pytest.fixture(scope="session")
def oauth_client():
    body = {
        "application_type": "private",
        "redirect_uris": ["https://client.example.org/callback"],
        "client_name": "usecases-test-client",
        "token_endpoint_auth_method": "client_secret_post",
        "contacts": ["usecases@example.org"],
        "scope": " ".join(READ_SCOPES),
    }
    resp = requests.post(f"{OAUTH}/registration", json=body, verify=False, timeout=30)
    assert resp.status_code < 400, f"client registration failed: {resp.status_code} {resp.text[:300]}"
    client = resp.json()
    client_id = _safe_id(client["client_id"])

    # New clients start disabled (oauth_clients.is_enabled = 0).
    db_query(f"UPDATE oauth_clients SET is_enabled = 1 WHERE client_id = '{client_id}'")

    yield client

    db_query(f"DELETE FROM api_token WHERE client_id = '{client_id}'")
    db_query(f"DELETE FROM oauth_clients WHERE client_id = '{client_id}'")


@pytest.fixture(scope="session")
def get_token(oauth_client):
    """Factory: password-grant access token for the given scopes."""
    def _get(scopes: list[str]) -> str:
        resp = requests.post(
            f"{OAUTH}/token",
            data={
                "grant_type": "password",
                "client_id": oauth_client["client_id"],
                "client_secret": oauth_client.get("client_secret", ""),
                "user_role": "users",
                "username": OE_USER,
                "password": OE_PASS,
                "scope": " ".join(scopes),
            },
            verify=False, timeout=30,
        )
        assert resp.status_code == 200, f"token request failed: {resp.status_code} {resp.text[:300]}"
        return resp.json()["access_token"]
    return _get


def _session(token: str) -> requests.Session:
    s = requests.Session()
    s.verify = False
    s.headers.update({"Authorization": f"Bearer {token}", "Accept": "application/json"})
    return s


@pytest.fixture(scope="session")
def api(get_token) -> requests.Session:
    """Authenticated session with the full read-only scope set."""
    return _session(get_token(READ_SCOPES))


@pytest.fixture(scope="session")
def narrow_api(get_token) -> requests.Session:
    """Session whose token may only read Patient resources."""
    return _session(get_token(["openid", "api:fhir", "user/Patient.read"]))
