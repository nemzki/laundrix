"""Integration tests against Didit's REAL sandbox. NOT run by default and NOT run in CI here.

Needs a Didit *sandbox-mode application* (create a second application and choose "sandbox"):
    DIDIT_SANDBOX_API_KEY=<that application's API key>
    DIDIT_SANDBOX_WORKFLOW_ID=<a workflow in that application>
Optional: DIDIT_SANDBOX_SCENARIO (a slug from the provider's sandbox catalogue, e.g. "approve")
Run:  pytest -m integration tests/integration

These verify the parts of the provider contract our client depends on. They deliberately do NOT
invent test documents or magic values; use the provider's own sandbox reference for those.
"""
import os
import uuid

import pytest

from app.identity.provider.base import ProviderAuthError, SessionNotFound
from app.identity.provider.didit import DiditProvider
from app.identity.statuses import PROVIDER_STATUS_MAP

API_KEY = os.getenv("DIDIT_SANDBOX_API_KEY")
WORKFLOW = os.getenv("DIDIT_SANDBOX_WORKFLOW_ID")

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not (API_KEY and WORKFLOW),
                       reason="set DIDIT_SANDBOX_API_KEY and DIDIT_SANDBOX_WORKFLOW_ID"),
]


def _provider(key=None):
    return DiditProvider(key or API_KEY, WORKFLOW,
                         sandbox_scenario=os.getenv("DIDIT_SANDBOX_SCENARIO") or None)


def test_create_session_returns_a_hosted_didit_url():
    session = _provider().create_session(f"laundrix-it:{uuid.uuid4()}", "https://example.com/return")
    uuid.UUID(session.session_id)
    assert session.url.startswith("https://") and "didit.me" in session.url


def test_same_vendor_data_returns_the_open_session_not_a_duplicate():
    ref = f"laundrix-it:{uuid.uuid4()}"
    a = _provider().create_session(ref, "https://example.com/return")
    b = _provider().create_session(ref, "https://example.com/return")
    assert a.session_id == b.session_id


def test_decision_status_is_one_we_know_how_to_map():
    p = _provider()
    s = p.create_session(f"laundrix-it:{uuid.uuid4()}", "https://example.com/return")
    assert p.get_decision(s.session_id).status in PROVIDER_STATUS_MAP


def test_bad_api_key_is_reported_as_an_auth_error():
    with pytest.raises(ProviderAuthError):
        _provider("definitely-not-a-key").create_session("laundrix-it:x", "https://example.com/return")


def test_unknown_session_is_not_found():
    with pytest.raises(SessionNotFound):
        _provider().get_decision(str(uuid.uuid4()))
