"""Didit webhook authentication (X-Signature-V2) — pure Python.

Didit signs HMAC-SHA256 over a canonical re-encoding of the JSON body: whole-valued floats
shortened to ints, keys sorted recursively, compact separators, Unicode preserved. Requests whose
X-Timestamp header OR signed body `timestamp` is more than 5 minutes from "now" are rejected, to
limit replay (the header alone is unsigned and therefore forgeable).
Reference: https://docs.didit.me/integration/webhooks
"""
import hashlib
import hmac
import json
import time
from typing import Optional

TOLERANCE_SECONDS = 300


class WebhookError(Exception):
    """Raised for any webhook that must be rejected. `reason` is for logs, never for the sender."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def _shorten_floats(data):
    if isinstance(data, dict):
        return {k: _shorten_floats(v) for k, v in data.items()}
    if isinstance(data, list):
        return [_shorten_floats(v) for v in data]
    if isinstance(data, float) and data.is_integer():
        return int(data)
    return data


def canonical_json(data) -> str:
    return json.dumps(
        _shorten_floats(data),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def compute_signature_v2(body: dict, secret: str) -> str:
    return hmac.new(
        secret.encode("utf-8"), canonical_json(body).encode("utf-8"), hashlib.sha256
    ).hexdigest()


def verify_signature_v2(
    body: dict,
    signature: Optional[str],
    timestamp: Optional[str],
    secret: Optional[str],
    *,
    now: Optional[float] = None,
    tolerance: int = TOLERANCE_SECONDS,
) -> None:
    """Return None if authentic; raise WebhookError otherwise."""
    if not signature or not timestamp or not secret:
        raise WebhookError("missing_header_or_secret")
    try:
        ts = int(timestamp)
    except (TypeError, ValueError):
        raise WebhookError("bad_timestamp")
    current = time.time() if now is None else now
    if abs(current - ts) > tolerance:
        raise WebhookError("stale_timestamp")
    try:
        expected = compute_signature_v2(body, secret)
    except (TypeError, ValueError):
        raise WebhookError("uncanonicalisable_body")
    if not hmac.compare_digest(expected.encode("utf-8"), signature.strip().lower().encode("utf-8")):
        raise WebhookError("bad_signature")

    # The X-Timestamp HEADER is not covered by the signature, so on its own it can be forged to
    # replay a captured request. The body's own `timestamp` IS signed (it is part of the canonical
    # JSON), so require that to be fresh as well. Didit refreshes it on every delivery attempt.
    body_ts = body.get("timestamp")
    if isinstance(body_ts, bool) or not isinstance(body_ts, (int, float)):
        raise WebhookError("missing_body_timestamp")
    if abs(current - body_ts) > tolerance:
        raise WebhookError("stale_body_timestamp")


def _reject_constant(name):
    raise ValueError(f"invalid JSON constant: {name}")


def parse_json_object(raw: bytes) -> dict:
    """Strict JSON parse: must be an object; NaN/Infinity are rejected."""
    try:
        data = json.loads(raw.decode("utf-8"), parse_constant=_reject_constant)
    except (UnicodeDecodeError, ValueError):
        raise WebhookError("malformed_json")
    if not isinstance(data, dict):
        raise WebhookError("body_not_object")
    return data
