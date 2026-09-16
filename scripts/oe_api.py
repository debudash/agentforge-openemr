"""Shared OpenEMR database and API access for the setup scripts and the test suite.

This module holds what both the laptop scripts and the Railway cron container need, with
no pytest dependency, so the same code paths run in every environment. `usecases/conftest.py`
re-exports these names, so `from conftest import db_query` keeps working.

Database access has three modes, chosen by `OE_DB_VIA`:

| mode              | how it reaches MariaDB                    | used by                          |
|-------------------|-------------------------------------------|----------------------------------|
| `docker` (default)| `docker compose exec` on the local stack   | laptop, local stack              |
| `railway`         | `railway ssh` into the openemr service     | laptop, Railway deployment       |
| `mysql`           | a direct connection (PyMySQL)              | the Railway cron container       |

Only `mysql` mode needs PyMySQL, and it is imported lazily so the other two modes run
without it.

@package   OpenEMR
@author    Debu Dash
@copyright Copyright (c) 2026 Debu Dash
@license   https://github.com/openemr/openemr/blob/master/LICENSE GNU General Public License 3
"""

from __future__ import annotations

import base64
import os
import re
import subprocess
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

import requests
import urllib3

urllib3.disable_warnings()

BASE_URL = os.environ.get("OPENEMR_BASE_URL", "https://localhost:9300").rstrip("/")
OE_USER = os.environ.get("OE_USER", "admin")
OE_PASS = os.environ.get("OE_PASS", "pass")

OAUTH = f"{BASE_URL}/oauth2/default"
FHIR = f"{BASE_URL}/apis/default/fhir"
REST = f"{BASE_URL}/apis/default/api"

COMPOSE_DIR = Path(__file__).resolve().parent.parent / "docker" / "development-easy"
PROJECT_DIR = Path(__file__).resolve().parent.parent

# Read-only scopes: the test suite never needs to write.
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

DB_VIA = os.environ.get("OE_DB_VIA", "docker")
RAILWAY_SERVICE = os.environ.get("RAILWAY_SERVICE", "openemr")
RAILWAY_DB_HOST = os.environ.get("OE_DB_HOST", "mysql.railway.internal")
RAILWAY_DB_USER = os.environ.get("OE_DB_USER", "openemr")

# Direct-connection settings (OE_DB_VIA=mysql). Railway's private network is IPv6 and takes
# a moment to come up in a fresh container, so connecting retries briefly.
MYSQL_HOST = os.environ.get("MYSQL_HOST", RAILWAY_DB_HOST)
MYSQL_PORT = int(os.environ.get("MYSQL_PORT", "3306"))
MYSQL_USER = os.environ.get("MYSQL_USER", RAILWAY_DB_USER)
MYSQL_DATABASE = os.environ.get("MYSQL_DATABASE", "openemr")
MYSQL_CONNECT_ATTEMPTS = int(os.environ.get("MYSQL_CONNECT_ATTEMPTS", "10"))

# `railway ssh` writes a key-usage banner to stdout on some platforms; drop it.
_BANNER_PREFIXES = ("Using SSH key", "Connecting to", "Connection to")


def _db_password() -> str:
    password = os.environ.get("OE_DB_PASS") or os.environ.get("MYSQL_PASSWORD") or os.environ.get("MYSQL_PASS") or ""
    assert password, "set OE_DB_PASS (or MYSQL_PASSWORD) to the openemr database user's password"
    return password


def _db_query_mysql(sql: str) -> list[list[str]]:
    import pymysql  # lazy: only this mode needs the driver

    last: Exception | None = None
    for attempt in range(1, MYSQL_CONNECT_ATTEMPTS + 1):
        try:
            connection = pymysql.connect(
                host=MYSQL_HOST, port=MYSQL_PORT, user=MYSQL_USER,
                password=_db_password(), database=MYSQL_DATABASE,
                connect_timeout=10, read_timeout=60, write_timeout=60, autocommit=True,
            )
            break
        except Exception as exc:  # noqa: BLE001 - private networking may not be up yet
            last = exc
            if attempt == MYSQL_CONNECT_ATTEMPTS:
                raise
            print(f"  database not reachable yet ({type(exc).__name__}), retry {attempt}/{MYSQL_CONNECT_ATTEMPTS}")
            time.sleep(min(2 * attempt, 10))
    else:  # pragma: no cover - the loop either breaks or raises
        raise RuntimeError(f"could not connect to the database: {last}")

    try:
        with connection.cursor() as cursor:
            cursor.execute(sql)
            rows = cursor.fetchall() or ()
    finally:
        connection.close()
    return [["" if value is None else str(value) for value in row] for row in rows]


def db_query(sql: str) -> list[list[str]]:
    """Run one SQL statement against the OpenEMR database; return rows as lists of strings."""
    if DB_VIA == "mysql":
        return _db_query_mysql(sql)

    env = {**os.environ, "MSYS_NO_PATHCONV": "1"}
    if DB_VIA == "railway":
        # Base64 keeps the SQL free of spaces and quotes: `railway ssh` passes the command
        # as argv, so an unencoded statement gets word-split before sh sees it.
        encoded = base64.b64encode(sql.encode()).decode()
        remote = (
            f"echo {encoded} | base64 -d | "
            f"mariadb -h {RAILWAY_DB_HOST} -u{RAILWAY_DB_USER} -p{_db_password()} openemr -N -B"
        )
        command = ["railway", "ssh", "--service", RAILWAY_SERVICE, "sh", "-c", remote]
        cwd = PROJECT_DIR  # the railway-linked project directory
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


@contextmanager
def api_session(scopes: list[str], client_name: str = "openemr-script") -> Iterator[requests.Session]:
    """Register a temporary OAuth client, yield an authenticated session, then delete it.

    New clients start disabled, so the row is enabled directly in the database, which is
    acceptable for a setup tool but never in production (AUDIT.md S6).
    """
    registration = requests.post(f"{OAUTH}/registration", verify=False, timeout=60, json={
        "application_type": "private",
        "redirect_uris": ["https://client.example.org/callback"],
        "client_name": client_name,
        "token_endpoint_auth_method": "client_secret_post",
        "contacts": ["admin@example.org"],
        "scope": " ".join(scopes),
    })
    assert registration.status_code < 400, f"client registration failed: {registration.status_code} {registration.text[:300]}"
    client = registration.json()
    client_id = _safe_id(client["client_id"])
    db_query(f"UPDATE oauth_clients SET is_enabled = 1 WHERE client_id = '{client_id}'")

    try:
        token_response = requests.post(f"{OAUTH}/token", verify=False, timeout=60, data={
            "grant_type": "password", "client_id": client_id,
            "client_secret": client.get("client_secret", ""),
            "user_role": "users", "username": OE_USER, "password": OE_PASS,
            "scope": " ".join(scopes),
        })
        assert token_response.status_code == 200, f"token request failed: {token_response.status_code} {token_response.text[:300]}"
        session = requests.Session()
        session.verify = False
        session.headers.update({
            "Authorization": f"Bearer {token_response.json()['access_token']}",
            "Content-Type": "application/json",
        })
        yield session
    finally:
        db_query(f"DELETE FROM api_token WHERE client_id = '{client_id}'")
        db_query(f"DELETE FROM api_refresh_token WHERE client_id = '{client_id}'")
        db_query(f"DELETE FROM oauth_clients WHERE client_id = '{client_id}'")
