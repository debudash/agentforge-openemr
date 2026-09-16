"""Shared fixtures: OAuth client, tokens, API sessions, and a DB helper.

Targets the local docker/development-easy stack. The dev stack uses a
self-signed certificate, so TLS verification is off (local only).
"""

import base64
import os
import re
import subprocess
from pathlib import Path

import pytest
import requests

BASE_URL = os.environ.get("OPENEMR_BASE_URL", "https://localhost:9300")
OE_USER = os.environ.get("OE_USER", "admin")
OE_PASS = os.environ.get("OE_PASS", "pass")

OAUTH = f"{BASE_URL}/oauth2/default"
FHIR = f"{BASE_URL}/apis/default/fhir"
REST = f"{BASE_URL}/apis/default/api"

COMPOSE_DIR = Path(__file__).resolve().parent.parent / "docker" / "development-easy"

# Read-only scopes: the suite never needs to write.
READ_SCOPES = [
    "openid",
    "api:fhir",
    "api:oemr",
    "user/Patient.read",
    "user/Condition.read",
    "user/MedicationRequest.read",
    "user/AllergyIntolerance.read",
    "user/Observation.read",
    "user/Encounter.read",
    "user/Immunization.read",
    "user/patient.read",
]


# Where the database lives: the local docker stack, or the Railway deployment.
#   OE_DB_VIA=railway  OE_DB_PASS=<openemr db password>  OPENEMR_BASE_URL=https://<app>.up.railway.app
DB_VIA = os.environ.get("OE_DB_VIA", "docker")
RAILWAY_SERVICE = os.environ.get("RAILWAY_SERVICE", "openemr")
RAILWAY_DB_HOST = os.environ.get("OE_DB_HOST", "mysql.railway.internal")
RAILWAY_DB_USER = os.environ.get("OE_DB_USER", "openemr")

# `railway ssh` writes a key-usage banner to stdout on some platforms; drop it.
_BANNER_PREFIXES = ("Using SSH key", "Connecting to", "Connection to")


def db_query(sql: str) -> list[list[str]]:
    """Run SQL against the OpenEMR database; return rows as lists of strings."""
    env = {**os.environ, "MSYS_NO_PATHCONV": "1"}

    if DB_VIA == "railway":
        password = os.environ.get("OE_DB_PASS")
        assert password, "set OE_DB_PASS (the openemr database user password) for OE_DB_VIA=railway"
        # Base64 keeps the SQL free of spaces and quotes: `railway ssh` passes the
        # command as argv, so an unencoded statement gets word-split before sh sees it.
        encoded = base64.b64encode(sql.encode()).decode()
        remote = (
            f"echo {encoded} | base64 -d | "
            f"mariadb -h {RAILWAY_DB_HOST} -u{RAILWAY_DB_USER} -p{password} openemr -N -B"
        )
        command = ["railway", "ssh", "--service", RAILWAY_SERVICE, "sh", "-c", remote]
        cwd = Path(__file__).resolve().parent.parent  # the railway-linked project directory
    else:
        command = ["docker", "compose", "exec", "-T", "mysql",
                   "mariadb", "-uroot", "-proot", "-N", "-B", "openemr", "-e", sql]
        cwd = COMPOSE_DIR

    result = subprocess.run(
        command, cwd=cwd, env=env, capture_output=True, text=True, check=True,
        shell=(os.name == "nt" and DB_VIA == "railway"),  # railway is a .cmd shim on Windows
    )
    return [
        line.split("\t") for line in result.stdout.splitlines()
        if line and not line.startswith(_BANNER_PREFIXES)
    ]


def _safe_id(value: str) -> str:
    # client_id is interpolated into SQL; only allow the characters OpenEMR issues.
    if not re.fullmatch(r"[A-Za-z0-9_\-]+", value):
        raise ValueError(f"unexpected client_id format: {value!r}")
    return value


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
