"""Didit API client (https://docs.didit.me).

Documented behaviour this relies on:
* Base URL https://verification.didit.me, auth via the `x-api-key` header.
* POST /v3/session/  {workflow_id, vendor_data, callback, ...} -> 201 {session_id, session_token,
  url, status, ...}. `vendor_data` makes it idempotent: an unfinished session for the same
  vendor_data is returned again instead of creating a duplicate.
* GET /v3/session/{session_id}/decision/ -> {status, ...plural per-feature arrays}.
* Auth failures are HTTP 403 (not 401); insufficient credits are 400; unknown session is 404.

The API key never leaves this class, is never logged, and is never sent over plain HTTP.
"""
import logging
import time
import uuid
from typing import Optional
from urllib.parse import urlparse

import requests

from app.identity.provider.base import (
    Decision, IdentityProvider, ProviderAuthError, ProviderError, ProviderRateLimited,
    ProviderRejectedRequest, ProviderUnavailable, SessionNotFound, VerificationSession,
)

log = logging.getLogger(__name__)

ALLOWED_URL_SUFFIX = ".didit.me"


def is_trusted_hosted_url(url: str) -> bool:
    """Only ever redirect a user to an https page on didit.me (guards against an open redirect)."""
    try:
        parsed = urlparse(url)
    except ValueError:
        return False
    host = (parsed.hostname or "").lower()
    return parsed.scheme == "https" and (host == "didit.me" or host.endswith(ALLOWED_URL_SUFFIX))


class DiditProvider(IdentityProvider):
    name = "didit"

    def __init__(
        self,
        api_key: str,
        workflow_id: str,
        base_url: str = "https://verification.didit.me",
        *,
        sandbox_scenario: Optional[str] = None,
        connect_timeout: float = 3.05,
        read_timeout: float = 10.0,
        http: Optional[requests.Session] = None,
        sleep=time.sleep,
    ):
        if not base_url.startswith("https://"):
            raise ValueError("Didit base URL must use https://")
        self._api_key = api_key
        self._workflow_id = workflow_id
        self._base = base_url.rstrip("/")
        self._sandbox_scenario = sandbox_scenario
        self._timeout = (connect_timeout, read_timeout)
        self._http = http or requests.Session()
        self._sleep = sleep

    # ------------------------------------------------------------------ HTTP core
    def _request(self, method: str, path: str, *, json_body=None, retries: int = 0, not_found_is_session=False):
        url = self._base + path
        headers = {"x-api-key": self._api_key, "Accept": "application/json"}
        attempt = 0
        while True:
            try:
                resp = self._http.request(
                    method, url, headers=headers, json=json_body,
                    timeout=self._timeout, allow_redirects=False,
                )
            except (requests.Timeout, requests.ConnectionError) as exc:
                if attempt < retries:
                    attempt += 1
                    self._sleep(0.4 * attempt)
                    continue
                log.warning("Didit %s %s failed: %s", method, path.split("?")[0], type(exc).__name__)
                raise ProviderUnavailable(type(exc).__name__) from exc

            status = resp.status_code
            if status in (200, 201):
                try:
                    data = resp.json()
                except ValueError as exc:
                    raise ProviderUnavailable("invalid JSON from provider") from exc
                if not isinstance(data, dict):
                    raise ProviderUnavailable("unexpected response shape")
                return data
            if status == 429:
                retry_after = resp.headers.get("Retry-After", "")
                raise ProviderRateLimited(retry_after=int(retry_after) if retry_after.isdigit() else None)
            if status >= 500:
                if attempt < retries:
                    attempt += 1
                    self._sleep(0.4 * attempt)
                    continue
                raise ProviderUnavailable(f"HTTP {status}")
            if status in (401, 403):
                raise ProviderAuthError("Didit rejected the API key or permissions")
            if status == 404 and not_found_is_session:
                raise SessionNotFound("unknown session")
            # Other 4xx (incl. 400 for no credits / invalid workflow): our request, not the user's ID.
            log.error("Didit %s %s -> HTTP %s", method, path.split("?")[0], status)
            raise ProviderRejectedRequest(f"HTTP {status}")

    # ------------------------------------------------------------------ operations
    def create_session(
        self, user_ref: str, callback_url: str, workflow_id: Optional[str] = None
    ) -> VerificationSession:
        body = {
            "workflow_id": workflow_id or self._workflow_id,
            "vendor_data": user_ref,
            "callback": callback_url,
        }
        if self._sandbox_scenario:
            body["sandbox_scenario"] = self._sandbox_scenario  # live applications reject this
        # Safe to retry once: an unfinished session for the same vendor_data is returned, not duplicated.
        data = self._request("POST", "/v3/session/", json_body=body, retries=1)

        session_id, url, status = data.get("session_id"), data.get("url"), data.get("status")
        if not (isinstance(session_id, str) and isinstance(url, str)):
            raise ProviderUnavailable("incomplete session response")
        if not is_trusted_hosted_url(url):
            log.error("Didit returned an untrusted hosted URL host; refusing to use it")
            raise ProviderRejectedRequest("untrusted session url")
        return VerificationSession(session_id=session_id, url=url, status=status or "Not Started")

    def get_decision(self, session_id: str) -> Decision:
        try:
            canonical = str(uuid.UUID(session_id))  # blocks path tricks like "../"
        except (ValueError, AttributeError, TypeError):
            raise SessionNotFound("malformed session id")
        data = self._request(
            "GET", f"/v3/session/{canonical}/decision/", retries=2, not_found_is_session=True,
        )
        status = data.get("status")
        if not isinstance(status, str):
            raise ProviderUnavailable("decision without status")
        return Decision(status=status, raw=data)
