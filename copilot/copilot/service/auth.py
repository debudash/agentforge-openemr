"""Request signing between the OpenEMR module (PHP) and this service.

The PHP module is the only caller. It signs every request with a shared secret:

    X-Copilot-Timestamp: <unix seconds>
    X-Copilot-Signature: hex(HMAC-SHA256(secret, "<ts>.<METHOD>.<path>.<raw body>"))

The service rejects missing or stale timestamps and any signature mismatch. The
browser never holds the secret and never talks to this service directly (PHI4).
"""

from __future__ import annotations

import hashlib
import hmac
import time


def signing_string(timestamp: str, method: str, path: str, body: bytes) -> bytes:
    return b".".join([timestamp.encode(), method.upper().encode(), path.encode(), body])


def sign(secret: str, timestamp: str, method: str, path: str, body: bytes) -> str:
    return hmac.new(secret.encode(), signing_string(timestamp, method, path, body), hashlib.sha256).hexdigest()


def verify(secret: str, timestamp: str | None, signature: str | None, method: str, path: str, body: bytes,
           skew_s: int = 300, now: float | None = None) -> tuple[bool, str]:
    if not secret:
        return False, "service has no shared secret configured"
    if not timestamp or not signature:
        return False, "missing signature headers"
    try:
        ts = int(timestamp)
    except ValueError:
        return False, "bad timestamp"
    if abs((now or time.time()) - ts) > skew_s:
        return False, "timestamp outside the allowed window"
    expected = sign(secret, timestamp, method, path, body)
    if not hmac.compare_digest(expected, signature.lower()):
        return False, "signature mismatch"
    return True, "ok"
