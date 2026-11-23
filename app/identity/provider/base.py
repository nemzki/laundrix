"""Provider-neutral types. The error classes are the important part: they let the rest of the app
tell "the provider/API failed" (never the user's fault) apart from "the user failed verification"
(which only ever arrives as a provider *decision*)."""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List, Optional


class ProviderError(Exception):
    """Base error for any problem talking to the identity provider."""
    code = "provider_error"
    retryable = False


class ProviderUnavailable(ProviderError):
    """Timeout, connection failure, or a 5xx. Safe to retry later."""
    code = "provider_unavailable"
    retryable = True


class ProviderRateLimited(ProviderUnavailable):
    """The provider says we are sending too many requests (may include a retry-after time)."""
    code = "provider_rate_limited"

    def __init__(self, message="rate limited", retry_after: Optional[int] = None):
        """Create the error and remember how many seconds to wait before retrying, if known."""
        super().__init__(message)
        self.retry_after = retry_after


class ProviderAuthError(ProviderError):
    """Our API key is missing/invalid/lacks permission (Didit answers 403, never 401)."""
    code = "provider_auth"


class ProviderRejectedRequest(ProviderError):
    """The provider refused the request itself (HTTP 400/other 4xx, e.g. no credits left)."""
    code = "provider_rejected_request"


class FaceNotDetected(ProviderRejectedRequest):
    """Didit answered 400 because the submitted image has no detectable face.
    This is a bad capture, not a provider outage and not a failed identity match."""
    code = "face_not_detected"


class SessionNotFound(ProviderError):
    """The provider has no verification session with that id."""
    code = "session_not_found"


@dataclass(frozen=True)
class VerificationSession:
    """A verification session created at the provider: its id, the hosted page URL and its status."""
    session_id: str
    url: str            # hosted page the user is redirected to
    status: str         # provider status string, e.g. "Not Started"


@dataclass(frozen=True)
class Decision:
    """The provider's decision for a session: its status text and the raw response (kept in memory only)."""
    status: str                                   # provider status string, e.g. "Approved"
    raw: dict = field(default_factory=dict, repr=False)  # in memory only; never persisted/logged


class IdentityProvider(ABC):
    """Blueprint that every identity provider must follow.

    Concrete providers (such as Didit) implement these methods, so the rest of the app does not
    depend on one specific company."""
    name = "abstract"

    @abstractmethod
    def create_session(
        self, user_ref: str, callback_url: str, workflow_id: Optional[str] = None
    ) -> VerificationSession:
        """`workflow_id` overrides the default workflow (used for the sign-in face check)."""

    @abstractmethod
    def get_decision(self, session_id: str) -> Decision: ...

    def passive_liveness(
        self,
        image_bytes: bytes,
        *,
        filename: str = "capture.jpg",
        vendor_data: Optional[str] = None,
    ) -> dict:
        """Run standalone passive liveness on one captured face image.

        Providers that do not support standalone liveness may keep this default
        implementation; callers should treat NotImplementedError as unsupported.
        """
        raise NotImplementedError("Standalone passive liveness is not supported")


    def face_search(
        self,
        image_bytes: bytes,
        *,
        filename: str = "capture.jpg",
        vendor_data: Optional[str] = None,
        similarity_threshold: int = 70,
        allow_multiple_faces: bool = False,
    ) -> dict:
        """Search the provider's enrolled face population for one reference image."""
        raise NotImplementedError("Standalone face search is not supported")
