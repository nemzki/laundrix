"""Didit API client (https://docs.didit.me).

Documented behaviour this relies on:
* Base URL https://verification.didit.me, auth via the `x-api-key` header.
* POST /v3/session/  {workflow_id, vendor_data, callback, ...} -> 201 {session_id, session_token,
  url, status, ...}. `vendor_data` makes it idempotent: an unfinished session for the same
  vendor_data is returned again instead of creating a duplicate.
* GET /v3/session/{session_id}/decision/ -> {status, ...plural per-feature arrays}.
* POST /v3/passive-liveness/ accepts multipart image (+ optional vendor_data).
* POST /v3/face-search/ accepts multipart image (+ optional search controls).
* Auth failures are HTTP 403 (not 401); request rejections are 4xx; unknown session is 404.

Standalone biometric POSTs are not retried: repeating a provider call after a network
failure could duplicate processing or billing. Raw provider reports are returned in memory
for the service layer to interpret; this client never persists images or results.

The API key never leaves this class, is never logged, and is never sent over plain HTTP.
"""
import logging
import os
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
MAX_BIOMETRIC_IMAGE_BYTES = 5 * 1024 * 1024
_IMAGE_TYPES = {
    ".jpg": ("image/jpeg", b"\xff\xd8\xff"),
    ".jpeg": ("image/jpeg", b"\xff\xd8\xff"),
    ".png": ("image/png", b"\x89PNG\r\n\x1a\n"),
}


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
        parsed = urlparse(base_url)

        if (
                parsed.scheme != "https"
                or parsed.hostname != "verification.didit.me"
                or parsed.port not in (None, 443)
                or parsed.username is not None
                or parsed.password is not None
                or parsed.path not in ("", "/")
                or parsed.query
                or parsed.fragment
        ):
            raise ValueError("Didit base URL must use the official HTTPS API host")
        self._api_key = api_key
        self._workflow_id = workflow_id
        self._base = base_url.rstrip("/")
        self._sandbox_scenario = sandbox_scenario
        self._timeout = (connect_timeout, read_timeout)
        self._http = http or requests.Session()
        self._sleep = sleep

    # ------------------------------------------------------------------ HTTP core
    def _request(
        self,
        method: str,
        path: str,
        *,
        json_body=None,
        form_data=None,
        files=None,
        retries: int = 0,
        not_found_is_session=False,
    ):
        url = self._base + path
        headers = {"x-api-key": self._api_key, "Accept": "application/json"}
        attempt = 0
        while True:
            try:
                request_kwargs = {
                    "headers": headers,
                    "timeout": self._timeout,
                    "allow_redirects": False,
                }
                if files is not None:
                    # requests must generate the multipart boundary itself.
                    request_kwargs["files"] = files
                    request_kwargs["data"] = form_data or {}
                elif form_data is not None:
                    request_kwargs["data"] = form_data
                else:
                    request_kwargs["json"] = json_body
                resp = self._http.request(method, url, **request_kwargs)
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

    # ------------------------------------------------------- standalone biometrics
    @staticmethod
    def _prepare_face_image(image_bytes: bytes, filename: str):
        """Validate a single JPEG/PNG image before sending it to Didit.

        The browser-provided MIME type is deliberately not trusted. The extension
        and file signature determine the MIME type used in the multipart request.
        """
        if not isinstance(image_bytes, bytes) or not image_bytes:
            raise ValueError("A non-empty face image is required")
        if len(image_bytes) > MAX_BIOMETRIC_IMAGE_BYTES:
            raise ValueError("Face image must not exceed 5 MB")
        if not isinstance(filename, str) or not filename.strip():
            raise ValueError("A valid image filename is required")

        safe_name = os.path.basename(filename.strip().replace("\\", "/"))
        extension = os.path.splitext(safe_name)[1].lower()
        image_type = _IMAGE_TYPES.get(extension)
        if image_type is None:
            raise ValueError("Face image must be a JPEG or PNG file")
        content_type, signature = image_type
        if not image_bytes.startswith(signature):
            raise ValueError("Face image content does not match its file type")
        return safe_name, content_type

    @staticmethod
    def _validate_vendor_data(vendor_data: Optional[str]) -> Optional[str]:
        if vendor_data is None:
            return None
        if not isinstance(vendor_data, str) or not vendor_data.strip():
            raise ValueError("vendor_data must be a non-empty string when provided")
        if len(vendor_data) > 256:
            raise ValueError("vendor_data is too long")
        return vendor_data.strip()

    def passive_liveness(
        self,
        image_bytes: bytes,
        *,
        filename: str = "capture.jpg",
        vendor_data: Optional[str] = None,
    ) -> dict:
        """Run Didit's standalone PASSIVE liveness check on a captured image.

        Returns the provider's JSON report unchanged. The caller must interpret
        its status and warnings; this method never grants access or stores images.
        """
        safe_name, content_type = self._prepare_face_image(image_bytes, filename)
        form_data = {"save_api_request": "false"}
        clean_vendor_data = self._validate_vendor_data(vendor_data)
        if clean_vendor_data is not None:
            form_data["vendor_data"] = clean_vendor_data
        return self._request(
            "POST",
            "/v3/passive-liveness/",
            form_data=form_data,
            files={"image": (safe_name, image_bytes, content_type)},
        )

    def face_search(
        self,
        image_bytes: bytes,
        *,
        filename: str = "capture.jpg",
        vendor_data: Optional[str] = None,
        similarity_threshold: int = 70,
        allow_multiple_faces: bool = False,
    ) -> dict:
        """Search Didit's enrolled face population using one reference image.

        Returns the provider's JSON report unchanged. The caller must reject
        ambiguous/weak matches and independently authorize the resolved account.
        """
        safe_name, content_type = self._prepare_face_image(image_bytes, filename)
        if isinstance(similarity_threshold, bool) or not isinstance(similarity_threshold, int):
            raise ValueError("similarity_threshold must be an integer from 0 to 100")
        if not 0 <= similarity_threshold <= 100:
            raise ValueError("similarity_threshold must be an integer from 0 to 100")
        if not isinstance(allow_multiple_faces, bool):
            raise ValueError("allow_multiple_faces must be a boolean")

        form_data = {
            "similarity_threshold": str(similarity_threshold),
            "save_api_request": "false",
        }
        clean_vendor_data = self._validate_vendor_data(vendor_data)
        if clean_vendor_data is not None:
            form_data["vendor_data"] = clean_vendor_data
        form_data["allow_multiple_faces"] = "true" if allow_multiple_faces else "false"
        return self._request(
            "POST",
            "/v3/face-search/",
            form_data=form_data,
            files={"image": (safe_name, image_bytes, content_type)},
        )

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
