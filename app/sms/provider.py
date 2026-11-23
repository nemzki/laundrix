"""UniSMS client. Talks to the provider and nothing else.

Documented API (https://unismsapi.com/docs/sms):
  POST {base}/sms                 JSON: recipient, content, sender_id, metadata
  GET  {base}/sms/{reference_id}  latest status
  auth: HTTP Basic, username = API secret key, password = "" (never Bearer)

Every outcome is normalised here so no other module parses provider responses:

  ACCEPTED   HTTP 201/200 with a usable reference. NOT proof of delivery; the provider's own status
             (pending / retrying / sent / failed) travels in `provider_status`.
  REJECTED   the provider definitely did not accept the request (auth, validation, credits, rate limit).
  AMBIGUOUS  we cannot tell whether it was queued (timeout, dropped connection, 5xx, unreadable reply).
             Callers must NOT resend automatically: that could text the customer twice.

The API secret and message text are never logged; error text is sanitised before it leaves this module."""
import logging
import re

import requests
from requests.auth import HTTPBasicAuth

log = logging.getLogger(__name__)

ACCEPTED, REJECTED, AMBIGUOUS = "accepted", "rejected", "ambiguous"
PROVIDER_STATUSES = ("pending", "retrying", "sent", "failed")
_REFERENCE_RE = re.compile(r"^[A-Za-z0-9_\-]{3,100}$")
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
_NUMBER = re.compile(r"\+?\d[\d\s\-]{6,}\d")


def safe_text(value, secret=None, limit=140):
    """Make provider-supplied text safe to store and display: no control characters, no phone numbers,
    no API secret, bounded length."""
    text = _CONTROL.sub(" ", str(value or ""))
    if secret:
        text = text.replace(secret, "[redacted]")
    text = _NUMBER.sub("[number]", text)
    return " ".join(text.split())[:limit]


class SendResult:
    """The result of trying to send an SMS: accepted, rejected or ambiguous, plus provider details."""
    def __init__(self, outcome, provider_status=None, reference_id=None, error=None, http_status=None):
        """Store the outcome, provider status, reference id, error text and HTTP status."""
        self.outcome, self.provider_status = outcome, provider_status
        self.reference_id, self.error, self.http_status = reference_id, error, http_status


class StatusResult:
    """The result of asking the provider for a message's delivery status."""
    def __init__(self, ok, provider_status=None, reference_id=None, error=None, fail_reason=None,
                 http_status=None, not_found=False):
        """Store whether the lookup worked, the provider status, reference id, error and failure reason."""
        self.ok, self.provider_status, self.reference_id = ok, provider_status, reference_id
        self.error, self.fail_reason = error, fail_reason
        self.http_status, self.not_found = http_status, not_found


class UniSMSClient:
    """Small client for the UniSMS HTTP API (send a message, check a message's status)."""
    def __init__(self, api_key, sender_id="Unisoft", base_url="https://unismsapi.com/api",
                 connect_timeout=3.05, read_timeout=10.0):
        """Store the API key, sender id, base URL and request timeouts."""
        self.api_key, self.sender_id = api_key, sender_id
        self.base_url = base_url.rstrip("/")
        self.timeout = (connect_timeout, read_timeout)

    def _auth(self):
        """Return the HTTP Basic credentials (the API key as username) used for every request."""
        return HTTPBasicAuth(self.api_key, "")

    def _reason(self, response):
        """Short, sanitised explanation taken from an error body (if there is one)."""
        try:
            data = response.json()
        except ValueError:
            return ""
        if isinstance(data, dict):
            for key in ("message", "error", "detail"):
                value = data.get(key)
                if isinstance(value, str) and value:
                    return safe_text(value, self.api_key, 120)
                if isinstance(value, dict) and isinstance(value.get("message"), str):
                    return safe_text(value["message"], self.api_key, 120)
        return ""

    # ------------------------------------------------------------------ send
    def send(self, recipient, content, metadata=None) -> SendResult:
        """Send one SMS and classify the result.

        200/201 -> accepted. Authentication, credit, rate-limit and other 4xx errors -> rejected.
        Timeouts, connection errors and 5xx -> ambiguous (the message may still have been queued)."""
        body = {"recipient": recipient, "content": content, "sender_id": self.sender_id}
        if metadata:
            body["metadata"] = {str(k): str(v) for k, v in metadata.items()}
        try:
            response = requests.post(f"{self.base_url}/sms", json=body, auth=self._auth(), timeout=self.timeout)
        except requests.exceptions.Timeout:
            return SendResult(AMBIGUOUS, error="The SMS provider did not respond in time. "
                                               "The message may or may not have been queued.")
        except requests.exceptions.RequestException:
            return SendResult(AMBIGUOUS, error="The connection to the SMS provider was interrupted. "
                                               "The message may or may not have been queued.")

        code = response.status_code
        if code in (200, 201):
            return self._parse_accepted(response)
        if code in (401, 403):
            return SendResult(REJECTED, error="SMS provider authentication failed. Check the API secret key.", http_status=code)
        if code == 402:
            return SendResult(REJECTED, error="The SMS account has insufficient credits.", http_status=code)
        if code == 429:
            return SendResult(REJECTED, error="The SMS provider is rate limiting requests. Try again later.", http_status=code)
        if 400 <= code < 500:
            reason = self._reason(response)
            return SendResult(REJECTED, http_status=code,
                              error="The SMS provider rejected the request" + (f": {reason}" if reason else "."))
        # 5xx and anything unexpected: the request may still have been queued.
        return SendResult(AMBIGUOUS, http_status=code,
                          error="The SMS provider reported a server error. The message may or may not have been queued.")

    def _parse_accepted(self, response) -> SendResult:
        """Read the provider's success reply and pull out the reference id and status.

        If the reply is not in the expected shape the result is ambiguous, not a failure."""
        try:
            data = response.json()
            message = data["message"]
            reference = message["reference_id"]
        except (ValueError, KeyError, TypeError):
            return SendResult(AMBIGUOUS, http_status=response.status_code,
                              error="The SMS provider's reply could not be understood. The message may have been queued.")
        if not isinstance(reference, str) or not _REFERENCE_RE.match(reference):
            return SendResult(AMBIGUOUS, http_status=response.status_code,
                              error="The SMS provider's reply could not be understood. The message may have been queued.")
        status = message.get("status") if isinstance(message, dict) else None
        status = status.lower() if isinstance(status, str) and status.lower() in PROVIDER_STATUSES else "pending"
        error = None
        if status == "failed":
            error = safe_text(message.get("fail_reason"), self.api_key) or "The SMS provider reported a failure."
        return SendResult(ACCEPTED, provider_status=status, reference_id=reference, error=error,
                          http_status=response.status_code)

    # ------------------------------------------------------------------ status
    def get_status(self, reference_id) -> StatusResult:
        """Ask the provider for the delivery status of a message by its reference id."""
        if not isinstance(reference_id, str) or not _REFERENCE_RE.match(reference_id):
            return StatusResult(False, error="The stored provider reference is not valid.")
        try:
            response = requests.get(f"{self.base_url}/sms/{reference_id}", auth=self._auth(), timeout=self.timeout)
        except requests.exceptions.RequestException:
            return StatusResult(False, error="The SMS provider could not be reached. Try again later.")

        code = response.status_code
        if code == 404:
            return StatusResult(False, http_status=code, not_found=True, error="The provider has no record of this message.")
        if code in (401, 403):
            return StatusResult(False, http_status=code, error="SMS provider authentication failed. Check the API secret key.")
        if code != 200:
            return StatusResult(False, http_status=code, error="The SMS provider is temporarily unavailable. Try again later.")
        try:
            message = response.json()["message"]
            status = message["status"].lower()
        except (ValueError, KeyError, TypeError, AttributeError):
            return StatusResult(False, http_status=code, error="The SMS provider's reply could not be understood.")
        if status not in PROVIDER_STATUSES:
            return StatusResult(False, http_status=code, error="The SMS provider returned an unrecognised status.")
        fail_reason = safe_text(message.get("fail_reason"), self.api_key) if status == "failed" else None
        return StatusResult(True, provider_status=status, reference_id=reference_id,
                            fail_reason=fail_reason or None, http_status=code)
