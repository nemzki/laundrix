import unittest
from datetime import datetime, timedelta

from app.identity.statuses import (
    ALLOWED_TRANSITIONS, APPLIED, INVALID, STALE, STATUS_COPY, UNCHANGED, UNKNOWN, IdvStatus,
    can_transition, extract_document_type, extract_reason_codes, map_provider_status,
    plan_transition, reason_category,
)


class ProviderStatusMapping(unittest.TestCase):
    def test_every_documented_didit_status_maps(self):
        expected = {
            "Not Started": "in_progress", "In Progress": "in_progress", "Awaiting User": "in_progress",
            "In Review": "pending_review", "Approved": "verified", "Declined": "rejected",
            "Resubmitted": "action_required", "Abandoned": "action_required",
            "Expired": "action_required", "Kyc Expired": "action_required",
        }
        for provider, ours in expected.items():
            self.assertEqual(map_provider_status(provider), ours, provider)

    def test_unknown_or_wrongly_cased_status_is_not_guessed(self):
        for bad in (None, "", "approved", "APPROVED", "Maybe"):
            self.assertIsNone(map_provider_status(bad), bad)

    def test_every_app_status_has_copy_and_transitions(self):
        for s in IdvStatus.ALL:
            self.assertIn(s, STATUS_COPY)
            self.assertIn(s, ALLOWED_TRANSITIONS)

    def test_user_facing_copy_does_not_leak_internals(self):
        text = " ".join(str(v) for c in STATUS_COPY.values() for v in c.values()).lower()
        for word in ("score", "threshold", "similarity", "fraud", "liveness"):
            self.assertNotIn(word, text)


class Transitions(unittest.TestCase):
    def test_success_path(self):
        self.assertEqual(plan_transition("in_progress", "Approved").new_status, "verified")

    def test_rejected_is_final(self):
        plan = plan_transition("rejected", "Approved")
        self.assertEqual(plan.outcome, INVALID)
        self.assertFalse(can_transition("rejected", "in_progress"))

    def test_verified_cannot_be_downgraded_except_by_expiry(self):
        self.assertEqual(plan_transition("verified", "Declined").outcome, INVALID)
        self.assertEqual(plan_transition("verified", "In Review").outcome, INVALID)
        expiry = plan_transition("verified", "Kyc Expired")
        self.assertEqual((expiry.outcome, expiry.new_status), (APPLIED, "action_required"))

    def test_manual_review_resolves_either_way(self):
        self.assertEqual(plan_transition("pending_review", "Approved").new_status, "verified")
        self.assertEqual(plan_transition("pending_review", "Declined").new_status, "rejected")

    def test_provider_failure_state_recovers_but_is_never_a_verdict(self):
        self.assertTrue(can_transition("error", "in_progress"))
        self.assertFalse(can_transition("error", "rejected"))
        self.assertFalse(can_transition("error", "verified"))

    def test_same_status_is_unchanged(self):
        self.assertEqual(plan_transition("in_progress", "In Progress").outcome, UNCHANGED)

    def test_unknown_status_is_reported_not_applied(self):
        self.assertEqual(plan_transition("in_progress", "Nonsense").outcome, UNKNOWN)

    def test_stale_event_is_ignored(self):
        now = datetime(2026, 10, 22, 12, 0, 0)
        plan = plan_transition("in_progress", "Approved", now - timedelta(minutes=5), now)
        self.assertEqual(plan.outcome, STALE)
        fresh = plan_transition("in_progress", "Approved", now + timedelta(seconds=1), now)
        self.assertEqual(fresh.outcome, APPLIED)

    def test_resubmission_returns_to_in_progress(self):
        self.assertTrue(can_transition("action_required", "in_progress"))


class DecisionReading(unittest.TestCase):
    DECISION = {
        "status": "Declined",
        "id_verifications": [{
            "document_type": "Passport", "document_number": "SECRET-123",
            "first_name": "Jane", "date_of_birth": "1990-01-01",
            "warnings": [{"risk": "DOCUMENT_EXPIRED", "log_type": "error"}],
        }],
        "face_matches": [{
            "score": 32.0,
            "warnings": [
                {"risk": "LOW_FACE_MATCH_SIMILARITY", "log_type": "error"},
                {"risk": "SOME_INFO_NOTE", "log_type": "information"},
            ],
        }],
    }

    def test_only_codes_are_extracted_never_personal_data(self):
        codes = extract_reason_codes(self.DECISION)
        self.assertEqual(codes, ["DOCUMENT_EXPIRED", "LOW_FACE_MATCH_SIMILARITY"])
        self.assertNotIn("SECRET-123", str(codes))

    def test_document_type_only(self):
        self.assertEqual(extract_document_type(self.DECISION), "Passport")

    def test_malformed_decisions_are_safe(self):
        for bad in (None, {}, [], "x", {"id_verifications": "nope"}, {"face_matches": [None, 5]}):
            self.assertEqual(extract_reason_codes(bad), [])
        self.assertIsNone(extract_document_type(None))

    def test_codes_are_validated_and_capped(self):
        decision = {"id_verifications": [{"warnings": [
            {"risk": "lower case"}, {"risk": "X"}, {"risk": "<script>"}, {"risk": 5},
        ] + [{"risk": f"CODE_{i}"} for i in range(30)]}]}
        codes = extract_reason_codes(decision)
        self.assertEqual(len(codes), 10)
        self.assertTrue(all(c.startswith("CODE_") for c in codes))

    def test_categories_are_coarse(self):
        self.assertEqual(reason_category(["DOCUMENT_EXPIRED"]), "document_expired")
        self.assertEqual(reason_category(["LOW_FACE_MATCH_SIMILARITY"]), "face")
        self.assertEqual(reason_category(["WHATEVER_NEW_CODE"]), "other")
        self.assertEqual(reason_category([]), "other")


if __name__ == "__main__":
    unittest.main()
