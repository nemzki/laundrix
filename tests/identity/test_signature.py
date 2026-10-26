import hashlib
import hmac
import unittest

from app.identity.signature import (
    WebhookError, canonical_json, compute_signature_v2, parse_json_object, verify_signature_v2,
)

SECRET = "unit-test-secret"
NOW = 1_800_000_000


def _body(**over):
    body = {
        "event_id": "9c0c8b8a-1111-4222-9333-444444444444", "webhook_type": "status.updated",
        "timestamp": NOW, "session_id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
        "status": "Approved", "vendor_data": "laundrix:7", "environment": "sandbox",
        "decision": {"face_matches": [{"score": 96.0, "status": "Approved"}], "note": "José"},
    }
    body.update(over)
    return body


class CanonicalForm(unittest.TestCase):
    def test_matches_documented_rules(self):
        # sorted keys, compact separators, unicode preserved, whole floats -> ints
        self.assertEqual(canonical_json({"b": 1.0, "a": "José", "c": [2.5, 3.0]}),
                         '{"a":"José","b":1,"c":[2.5,3]}')

    def test_signature_is_plain_hmac_sha256_of_that_string(self):
        body = {"b": 1.0, "a": "José"}
        expected = hmac.new(SECRET.encode(), '{"a":"José","b":1}'.encode(), hashlib.sha256).hexdigest()
        self.assertEqual(compute_signature_v2(body, SECRET), expected)


class Verification(unittest.TestCase):
    def sign(self, body):
        return compute_signature_v2(body, SECRET)

    def test_valid_signature_passes(self):
        body = _body()
        verify_signature_v2(body, self.sign(body), str(NOW), SECRET, now=NOW)

    def test_uppercase_hex_header_is_tolerated(self):
        body = _body()
        verify_signature_v2(body, self.sign(body).upper(), str(NOW), SECRET, now=NOW)

    def test_tampered_decision_is_rejected(self):
        body = _body()
        sig = self.sign(body)
        body["decision"]["face_matches"][0]["status"] = "Declined"  # attacker edits the verdict
        with self.assertRaises(WebhookError) as ctx:
            verify_signature_v2(body, sig, str(NOW), SECRET, now=NOW)
        self.assertEqual(ctx.exception.reason, "bad_signature")

    def test_wrong_secret_is_rejected(self):
        body = _body()
        with self.assertRaises(WebhookError):
            verify_signature_v2(body, compute_signature_v2(body, "other"), str(NOW), SECRET, now=NOW)

    def test_stale_timestamp_is_rejected_replay_protection(self):
        body = _body()
        with self.assertRaises(WebhookError) as ctx:
            verify_signature_v2(body, self.sign(body), str(NOW), SECRET, now=NOW + 301)
        self.assertEqual(ctx.exception.reason, "stale_timestamp")
        verify_signature_v2(body, self.sign(body), str(NOW), SECRET, now=NOW + 300)  # edge ok

    def test_replay_with_forged_fresh_header_is_rejected_via_signed_body_timestamp(self):
        # Attacker replays an OLD captured body+signature but sets a brand-new X-Timestamp header.
        old_body = _body(timestamp=NOW - 1000)
        sig = self.sign(old_body)
        with self.assertRaises(WebhookError) as ctx:
            verify_signature_v2(old_body, sig, str(NOW), SECRET, now=NOW)
        self.assertEqual(ctx.exception.reason, "stale_body_timestamp")

    def test_body_without_a_timestamp_is_rejected(self):
        body = _body()
        del body["timestamp"]
        with self.assertRaises(WebhookError) as ctx:
            verify_signature_v2(body, self.sign(body), str(NOW), SECRET, now=NOW)
        self.assertEqual(ctx.exception.reason, "missing_body_timestamp")
        body["timestamp"] = True  # bool is not a timestamp
        with self.assertRaises(WebhookError):
            verify_signature_v2(body, self.sign(body), str(NOW), SECRET, now=NOW)

    def test_future_timestamp_is_rejected_too(self):
        body = _body()
        with self.assertRaises(WebhookError):
            verify_signature_v2(body, self.sign(body), str(NOW), SECRET, now=NOW - 400)

    def test_missing_or_garbage_headers(self):
        body = _body()
        sig = self.sign(body)
        for signature, ts, secret in [(None, str(NOW), SECRET), (sig, None, SECRET),
                                      (sig, str(NOW), None), ("", str(NOW), SECRET)]:
            with self.assertRaises(WebhookError):
                verify_signature_v2(body, signature, ts, secret, now=NOW)
        with self.assertRaises(WebhookError) as ctx:
            verify_signature_v2(body, sig, "not-a-number", SECRET, now=NOW)
        self.assertEqual(ctx.exception.reason, "bad_timestamp")

    def test_non_ascii_signature_header_does_not_crash(self):
        with self.assertRaises(WebhookError):
            verify_signature_v2(_body(), "ünïcode", str(NOW), SECRET, now=NOW)


class StrictParsing(unittest.TestCase):
    def test_object_ok(self):
        self.assertEqual(parse_json_object(b'{"a": 1}'), {"a": 1})

    def test_rejects_non_objects_garbage_and_nan(self):
        for raw in (b"[1,2]", b"nope", b"\xff\xfe", b'{"a": NaN}', b'{"a": Infinity}', b'"str"'):
            with self.assertRaises(WebhookError):
                parse_json_object(raw)


if __name__ == "__main__":
    unittest.main()
