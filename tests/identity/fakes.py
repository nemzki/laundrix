"""A scriptable stand-in for the identity provider. Used ONLY in automated tests; it proves how
OUR code reacts to given provider behaviour, not how the real provider behaves."""
import uuid

from app.identity.provider.base import (
    Decision, IdentityProvider, SessionNotFound, VerificationSession,
)


class FakeProvider(IdentityProvider):
    name = "didit"

    def __init__(self):
        self.user_refs, self.callbacks, self.workflows = [], [], []
        self.calls = {"create": 0, "decision": 0}
        self.create_error = None          # set to an exception instance to make create_session fail
        self.decision_error = None
        self.decision_status = "In Progress"
        self.decision_raw = {}
        self._open = {}                   # user_ref -> session_id (mimics Didit's vendor_data idempotency)

    def create_session(self, user_ref, callback_url, workflow_id=None):
        self.calls["create"] += 1
        if self.create_error:
            raise self.create_error
        self.user_refs.append(user_ref)
        self.callbacks.append(callback_url)
        self.workflows.append(workflow_id)       # None = the default (ID verification) workflow
        sid = self._open.setdefault(user_ref, str(uuid.uuid4()))
        return VerificationSession(sid, f"https://verify.didit.me/session/{sid[:8]}", "Not Started")

    def finish(self, user_ref):
        """The provider session reached a final state, so the next create_session is a new one."""
        self._open.pop(user_ref, None)

    def get_decision(self, session_id):
        self.calls["decision"] += 1
        if self.decision_error:
            raise self.decision_error
        return Decision(status=self.decision_status, raw=self.decision_raw)
