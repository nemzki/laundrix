
import unittest

from app.identity.liveness import is_approved_passive_liveness


class TestPassiveLivenessValidation(unittest.TestCase):
    def test_accepts_approved_passive_liveness(self):
        report = {
            "request_id": "test-request",
            "liveness": {
                "status": "Approved",
                "method": "PASSIVE",
                "score": 95,
                "warnings": [],
            },
        }

        self.assertTrue(is_approved_passive_liveness(report))

    def test_rejects_non_approved_status(self):
        for status in ("Declined", "In Review", "", None):
            with self.subTest(status=status):
                report = {
                    "liveness": {
                        "status": status,
                        "method": "PASSIVE",
                    }
                }
                self.assertFalse(is_approved_passive_liveness(report))

    def test_rejects_non_passive_method(self):
        for method in ("ACTIVE", "", None):
            with self.subTest(method=method):
                report = {
                    "liveness": {
                        "status": "Approved",
                        "method": method,
                    }
                }
                self.assertFalse(is_approved_passive_liveness(report))

    def test_rejects_missing_or_malformed_liveness_envelope(self):
        invalid_reports = (
            None,
            [],
            {},
            {"status": "Approved", "method": "PASSIVE"},
            {"liveness": None},
            {"liveness": []},
            {"liveness": {"status": "Approved"}},
            {"liveness": {"method": "PASSIVE"}},
        )

        for report in invalid_reports:
            with self.subTest(report=report):
                self.assertFalse(is_approved_passive_liveness(report))


if __name__ == "__main__":
    unittest.main()
