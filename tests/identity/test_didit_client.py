"""Unit tests for the Didit client using a FAKE HTTP layer.

These prove how our client behaves for given responses. They do NOT prove Didit's real API
behaves this way - that is what tests/integration/test_didit_sandbox.py is for.
"""
import unittest

import requests

from app.identity.provider.base import (
    ProviderAuthError, ProviderRateLimited, ProviderRejectedRequest, ProviderUnavailable,
    SessionNotFound,
)
from app.identity.provider.didit import DiditProvider, is_trusted_hosted_url

SESSION_ID = "11111111-2222-3333-4444-555555555555"
KEY = "super-secret-api-key"


class FakeResponse:
    def __init__(self, status=200, body=None, headers=None, bad_json=False):
        self.status_code, self._body, self.headers, self._bad = status, body, headers or {}, bad_json

    def json(self):
        if self._bad:
            raise ValueError("bad json")
        return self._body


class FakeHttp:
    """Plays back a script of responses/exceptions and records every call."""

    def __init__(self, *script):
        self.script, self.calls = list(script), []

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def provider(http, **kw):
    return DiditProvider(KEY, "wf-1", "https://verification.didit.me", http=http,
                         sleep=lambda s: None, **kw)


OK_SESSION = {"session_id": SESSION_ID, "url": "https://verify.didit.me/session/abc",
              "status": "Not Started", "session_token": "tok"}


class CreateSession(unittest.TestCase):
    def test_success_uses_documented_endpoint_headers_and_body(self):
        http = FakeHttp(FakeResponse(201, OK_SESSION))
        s = provider(http).create_session("laundrix:7", "https://app.example/identity/return")
        method, url, kw = http.calls[0]
        self.assertEqual((method, url), ("POST", "https://verification.didit.me/v3/session/"))
        self.assertEqual(kw["headers"]["x-api-key"], KEY)
        self.assertEqual(kw["json"], {"workflow_id": "wf-1", "vendor_data": "laundrix:7",
                                      "callback": "https://app.example/identity/return"})
        self.assertFalse(kw["allow_redirects"])
        self.assertEqual(kw["timeout"], (3.05, 10.0))
        self.assertEqual((s.session_id, s.url, s.status), (SESSION_ID, OK_SESSION["url"], "Not Started"))

    def test_workflow_override_is_sent_and_default_is_used_otherwise(self):
        # the sign-in face check uses a different (Biometric Authentication) workflow
        override = FakeHttp(FakeResponse(201, OK_SESSION))
        provider(override).create_session("laundrix:7", "https://x/y", workflow_id="bio-wf")
        self.assertEqual(override.calls[0][2]["json"]["workflow_id"], "bio-wf")
        self.assertEqual(override.calls[0][2]["json"]["vendor_data"], "laundrix:7")  # same person ref
        default = FakeHttp(FakeResponse(201, OK_SESSION))
        provider(default).create_session("laundrix:7", "https://x/y")
        self.assertEqual(default.calls[0][2]["json"]["workflow_id"], "wf-1")

    def test_sandbox_scenario_only_sent_when_configured(self):
        with_s = FakeHttp(FakeResponse(201, OK_SESSION))
        provider(with_s, sandbox_scenario="approve").create_session("u", "https://x/y")
        self.assertEqual(with_s.calls[0][2]["json"]["sandbox_scenario"], "approve")
        without = FakeHttp(FakeResponse(201, OK_SESSION))
        provider(without).create_session("u", "https://x/y")
        self.assertNotIn("sandbox_scenario", without.calls[0][2]["json"])

    def test_auth_error_is_403_not_retried_and_never_leaks_key(self):
        http = FakeHttp(FakeResponse(403, {"detail": "no"}))
        with self.assertRaises(ProviderAuthError) as ctx:
            provider(http).create_session("u", "https://x/y")
        self.assertEqual(len(http.calls), 1)
        self.assertNotIn(KEY, str(ctx.exception))

    def test_401_is_treated_like_403(self):
        with self.assertRaises(ProviderAuthError):
            provider(FakeHttp(FakeResponse(401))).create_session("u", "https://x/y")

    def test_400_such_as_no_credits_is_a_request_rejection(self):
        with self.assertRaises(ProviderRejectedRequest):
            provider(FakeHttp(FakeResponse(400, {"detail": "insufficient credits"}))).create_session("u", "https://x/y")

    def test_timeout_is_retried_once_then_reported_as_unavailable_not_a_failed_check(self):
        http = FakeHttp(requests.Timeout(), requests.Timeout())
        with self.assertRaises(ProviderUnavailable):
            provider(http).create_session("u", "https://x/y")
        self.assertEqual(len(http.calls), 2)

    def test_retry_can_recover(self):
        http = FakeHttp(requests.ConnectionError(), FakeResponse(201, OK_SESSION))
        self.assertEqual(provider(http).create_session("u", "https://x/y").session_id, SESSION_ID)

    def test_5xx_is_unavailable(self):
        with self.assertRaises(ProviderUnavailable):
            provider(FakeHttp(FakeResponse(502), FakeResponse(502))).create_session("u", "https://x/y")

    def test_rate_limit_is_not_hammered_and_keeps_retry_after(self):
        http = FakeHttp(FakeResponse(429, headers={"Retry-After": "30"}))
        with self.assertRaises(ProviderRateLimited) as ctx:
            provider(http).create_session("u", "https://x/y")
        self.assertEqual(ctx.exception.retry_after, 30)
        self.assertEqual(len(http.calls), 1)
        self.assertTrue(ctx.exception.retryable)

    def test_garbage_or_incomplete_responses_are_unavailable(self):
        for resp in (FakeResponse(201, bad_json=True), FakeResponse(201, []),
                     FakeResponse(201, {"session_id": SESSION_ID})):
            with self.assertRaises(ProviderUnavailable):
                provider(FakeHttp(resp)).create_session("u", "https://x/y")

    def test_untrusted_hosted_url_is_refused(self):
        for url in ("http://verify.didit.me/s/1", "https://evil.example/didit.me",
                    "https://didit.me.evil.example/s", "https://evildidit.me/s", "javascript:alert(1)"):
            bad = dict(OK_SESSION, url=url)
            with self.assertRaises(ProviderRejectedRequest, msg=url):
                provider(FakeHttp(FakeResponse(201, bad))).create_session("u", "https://x/y")


class TrustedUrl(unittest.TestCase):
    def test_cases(self):
        self.assertTrue(is_trusted_hosted_url("https://verify.didit.me/session/abc"))
        self.assertTrue(is_trusted_hosted_url("https://didit.me/x"))
        self.assertFalse(is_trusted_hosted_url("http://verify.didit.me/x"))
        self.assertFalse(is_trusted_hosted_url("https://verify.didit.me.attacker.io/x"))
        self.assertFalse(is_trusted_hosted_url(""))


class GetDecision(unittest.TestCase):
    def test_success_hits_documented_path(self):
        http = FakeHttp(FakeResponse(200, {"status": "Approved", "id_verifications": []}))
        d = provider(http).get_decision(SESSION_ID)
        self.assertEqual(d.status, "Approved")
        self.assertEqual(http.calls[0][:2],
                         ("GET", f"https://verification.didit.me/v3/session/{SESSION_ID}/decision/"))

    def test_5xx_retried_twice_then_unavailable(self):
        http = FakeHttp(FakeResponse(503), FakeResponse(503), FakeResponse(503))
        with self.assertRaises(ProviderUnavailable):
            provider(http).get_decision(SESSION_ID)
        self.assertEqual(len(http.calls), 3)

    def test_unknown_session_404(self):
        with self.assertRaises(SessionNotFound):
            provider(FakeHttp(FakeResponse(404, {"detail": "Not found."}))).get_decision(SESSION_ID)

    def test_malformed_session_id_never_reaches_the_network(self):
        http = FakeHttp()
        for bad in ("../../admin", "abc", "", None):
            with self.assertRaises(SessionNotFound):
                provider(http).get_decision(bad)
        self.assertEqual(http.calls, [])

    def test_decision_without_status_is_unavailable(self):
        with self.assertRaises(ProviderUnavailable):
            provider(FakeHttp(FakeResponse(200, {"nope": 1}))).get_decision(SESSION_ID)


class Construction(unittest.TestCase):
    def test_plain_http_base_url_is_refused(self):
        with self.assertRaises(ValueError):
            DiditProvider(KEY, "wf", "http://verification.didit.me")


if __name__ == "__main__":
    unittest.main()
