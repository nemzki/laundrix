
"""Resolve a Didit Face Search result to an eligible Laundrix staff account."""

import math
import re
from numbers import Real

from app.extensions import db
from app.identity import services as idv
from app.models import Role, User


FACE_MATCH_MIN_SIMILARITY = 90.0

_VENDOR_DATA_PATTERN = re.compile(r"laundrix:([1-9][0-9]*)\Z")


def _extract_report(report):
    """Accept one documented response envelope; reject ambiguous envelopes."""
    if not isinstance(report, dict):
        return None

    if "face_search" in report:
        # Reject ambiguous top-level fields when using the nested envelope.
        if any(key in report for key in ("status", "matches", "total_matches")):
            return None

        envelope = report["face_search"]
    else:
        envelope = report

    if not isinstance(envelope, dict):
        return None

    status = envelope.get("status")
    matches = envelope.get("matches")
    total_matches = envelope.get("total_matches")

    if not isinstance(status, str) or status.strip().casefold() != "approved":
        return None

    if not isinstance(matches, list):
        return None

    if (
        isinstance(total_matches, bool)
        or not isinstance(total_matches, int)
        or total_matches != len(matches)
    ):
        return None

    # Never guess between multiple candidates.
    if len(matches) != 1:
        return None

    return matches[0]


def _extract_similarity(match):
    """Normalize one documented Didit score format to a percentage."""
    has_percentage = "similarity_percentage" in match
    has_score = "similarity_score" in match

    # Reject ambiguous or missing score representations.
    if has_percentage == has_score:
        return None

    field = "similarity_percentage" if has_percentage else "similarity_score"
    value = match.get(field)

    if isinstance(value, bool) or not isinstance(value, Real):
        return None

    value = float(value)

    if not math.isfinite(value):
        return None

    if field == "similarity_percentage":
        if not 0.0 <= value <= 100.0:
            return None
        return value

    # Didit's similarity_score example uses a fraction from 0 to 1.
    if not 0.0 <= value <= 1.0:
        return None

    return value * 100.0


def _user_id_from_vendor_data(value):
    """Extract only a canonical, positive Laundrix user ID."""
    if not isinstance(value, str):
        return None

    match = _VENDOR_DATA_PATTERN.fullmatch(value)
    if match is None:
        return None

    try:
        return int(match.group(1))
    except (ValueError, OverflowError):
        return None


def resolve_face_search_identity(report):
    """Return an eligible enrolled staff User, or None when validation fails.

    This function does not create sessions or persist provider response data.
    """
    match = _extract_report(report)

    if not isinstance(match, dict):
        return None

    if match.get("status") != "Approved":
        return None

    if match.get("is_blocklisted") is not False:
        return None

    similarity = _extract_similarity(match)
    if similarity is None or similarity < FACE_MATCH_MIN_SIMILARITY:
        return None

    user_id = _user_id_from_vendor_data(match.get("vendor_data"))
    if user_id is None:
        return None

    user = db.session.get(User, user_id)
    if user is None:
        return None

    if user.role != Role.STAFF:
        return None

    if not user.is_operational:
        return None

    if not idv.has_verified_identity(user):
        return None

    return user
