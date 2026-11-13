
"""Orchestrate the biometric checks required for staff face login."""

from app.identity.face_search import resolve_face_search_identity
from app.identity.liveness import is_approved_passive_liveness
from app.identity.provider import get_idv_provider


FACE_SEARCH_SIMILARITY_THRESHOLD = 90


def authenticate_with_face(image_bytes: bytes, *, filename: str = "capture.jpg"):
    """Return an eligible staff user, or None when verification fails.

    Provider errors are allowed to propagate so the route can distinguish
    provider failures from an unsuccessful identity verification.
    """
    provider = get_idv_provider()

    # Step 1: Verify that the captured image passes passive liveness.
    liveness_report = provider.passive_liveness(
        image_bytes,
        filename=filename,
    )

    if not is_approved_passive_liveness(liveness_report):
        return None

    # Step 2: Search for an enrolled face only after liveness approval.
    face_report = provider.face_search(
        image_bytes,
        filename=filename,
        similarity_threshold=FACE_SEARCH_SIMILARITY_THRESHOLD,
        allow_multiple_faces=False,
    )

    # Step 3: Resolve and independently authorize the matched staff account.
    return resolve_face_search_identity(face_report)
