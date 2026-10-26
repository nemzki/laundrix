"""Provider-neutral types. The error classes are the important part: they let the rest of the app
tell "the provider/API failed" (never the user's fault) apart from "the user failed verification"
(which only ever arrives as a provider *decision*)."""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List, Optional


class ProviderError(Exception):
    code = "provider_error"
    retryable = False


class ProviderUnavailable(ProviderError):
    """Timeout, connection failure, or a 5xx. Safe to retry later."""
    code = "provider_unavailable"
    retryable = True


class ProviderRateLimited(ProviderUnavailable):
    code = "provider_rate_limited"

    def __init__(self, message="rate limited", retry_after: Optional[int] = None):
        super().__init__(message)
        self.retry_after = retry_after


class ProviderAuthError(ProviderError):
    """Our API key is missing/invalid/lacks permission (Didit answers 403, never 401)."""
    code = "provider_auth"


class ProviderRejectedRequest(ProviderError):
    """The provider refused the request itself (HTTP 400/other 4xx, e.g. no credits left)."""
    code = "provider_rejected_request"


class SessionNotFound(ProviderError):
    code = "session_not_found"


@dataclass(frozen=True)
class VerificationSession:
    session_id: str
    url: str            # hosted page the user is redirected to
    status: str         # provider status string, e.g. "Not Started"


@dataclass(frozen=True)
class Decision:
    status: str                                   # provider status string, e.g. "Approved"
    raw: dict = field(default_factory=dict, repr=False)  # in memory only; never persisted/logged


class IdentityProvider(ABC):
    name = "abstract"

    @abstractmethod
    def create_session(
        self, user_ref: str, callback_url: str, workflow_id: Optional[str] = None
    ) -> VerificationSession:
        """`workflow_id` overrides the default workflow (used for the sign-in face check)."""

    @abstractmethod
    def get_decision(self, session_id: str) -> Decision: ...
