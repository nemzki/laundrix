
"""Resolve a Didit Face Search result to an eligible Laundrix staff account."""

import logging
import math
import re
from numbers import Real

from flask import current_app

from app.extensions import db
from app.identity import services as idv
from app.models import Role, User


log = logging.getLogger(__name__)

# Defaults. Override with FACE_LOGIN_MIN_SIMILARITY / FACE_LOGIN_MIN_MARGIN in .env after calibrating
# against the "Face Search diagnostic" log lines (see docs/face_login_guide.md).
FACE_MATCH_MIN_SIMILARITY = 90.0
FACE_MATCH_MIN_MARGIN = 5.0

_VENDOR_DATA_PATTERN = re.compile(r"laundrix:([1-9][0-9]*)\Z")


def _reject(reason):
    """Log a safe rejection reason and return None."""
    log.warning("Face Search rejected: %s", reason)
    return None


def _extract_report(report):
    """Validate the response envelope and return its candidate list."""
    if not isinstance(report, dict):
        _reject("response is not a dictionary.")
        return None

    if "face_search" in report:
        if any(key in report for key in ("status", "matches", "total_matches")):
            _reject("ambiguous response envelope.")
            return None
        envelope = report["face_search"]
    else:
        envelope = report

    if not isinstance(envelope, dict):
        _reject("face_search envelope is invalid.")
        return None

    status = envelope.get("status")
    matches = envelope.get("matches")
    total_matches = envelope.get("total_matches")

    if not isinstance(status, str) or status.strip().casefold() != "approved":
        _reject("response status is not approved.")
        return None

    if not isinstance(matches, list):
        _reject("matches field is not a list.")
        return None

    if (
        isinstance(total_matches, bool)
        or not isinstance(total_matches, int)
        or total_matches != len(matches)
    ):
        _reject("total_matches does not match the returned matches.")
        return None

    if not matches:
        _reject("no face matches returned.")
        return None

    if not all(isinstance(match, dict) for match in matches):
        _reject("one or more face match entries are invalid.")
        return None

    return matches


def _extract_similarity(match):
    """Normalize one documented Didit score format to a percentage."""
    has_percentage = "similarity_percentage" in match
    has_score = "similarity_score" in match

    if has_percentage == has_score:
        _reject("similarity field is missing or ambiguous.")
        return None

    field = "similarity_percentage" if has_percentage else "similarity_score"
    value = match.get(field)

    if isinstance(value, bool) or not isinstance(value, Real):
        _reject("similarity value has an invalid type.")
        return None

    value = float(value)

    if not math.isfinite(value):
        _reject("similarity value is not finite.")
        return None

    if field == "similarity_percentage":
        if not 0.0 <= value <= 100.0:
            _reject("similarity percentage is outside the valid range.")
            return None
        return value

    if not 0.0 <= value <= 1.0:
        _reject("similarity score is outside the valid range.")
        return None

    return value * 100.0


def _user_id_from_vendor_data(value):
    """Extract only a canonical, positive Laundrix user ID."""
    if not isinstance(value, str):
        _reject("vendor_data is missing or is not a string.")
        return None

    match = _VENDOR_DATA_PATTERN.fullmatch(value)
    if match is None:
        _reject("vendor_data does not match the expected format.")
        return None

    try:
        return int(match.group(1))
    except (ValueError, OverflowError):
        _reject("vendor_data contains an invalid user ID.")
        return None


def _threshold(name, default):
    try:
        value = float(current_app.config.get(name, default))
    except (TypeError, ValueError, RuntimeError):
        return default
    return value if 0.0 < value <= 100.0 else default


def resolve_face_search_identity(report):
    """Return one unambiguous eligible enrolled staff User, or None.

    Didit returns up to 5 matches and the SAME person usually appears several times (one entry per
    verification session that stored their face). Matches are therefore grouped by Laundrix user:
    the best score per user decides, and a different user must trail it by a safe margin.
    """
    matches = _extract_report(report)
    if matches is None:
        return None

    min_similarity = _threshold("FACE_LOGIN_MIN_SIMILARITY", FACE_MATCH_MIN_SIMILARITY)
    min_margin = _threshold("FACE_LOGIN_MIN_MARGIN", FACE_MATCH_MIN_MARGIN)

    log.warning("Didit Face Search returned %d candidate(s).", len(matches))

    best_by_user = {}          # user_id -> best similarity among that user's approved matches
    for match in matches:
        similarity = _extract_similarity(match)
        vendor_data = match.get("vendor_data", "")
        safe_reference = (
            vendor_data
            if isinstance(vendor_data, str) and _VENDOR_DATA_PATTERN.fullmatch(vendor_data)
            else "invalid-or-missing"
        )
        log.warning(
            "Face Search diagnostic: reference=%s, similarity=%s, source=%s, api_service=%s, "
            "session_number=%s, verification_date=%s, status=%s, blocklisted=%s",
            safe_reference, similarity, match.get("source"), match.get("api_service"),
            match.get("session_number"), match.get("verification_date"),
            match.get("status"), match.get("is_blocklisted"),
        )
        if similarity is None:
            return None

        if match.get("is_blocklisted") is not False:
            if similarity >= min_similarity:
                return _reject("a strong match is blocklisted or has no explicit false value.")
            continue
        if match.get("status") != "Approved":
            continue            # declined / in-review sessions never identify anyone

        user_id = _user_id_from_vendor_data(vendor_data)
        if user_id is None:
            if similarity >= min_similarity:
                return _reject("a strong match has no valid Laundrix reference.")
            continue
        if similarity > best_by_user.get(user_id, -1.0):
            best_by_user[user_id] = similarity

    if not best_by_user:
        return _reject("no approved candidate returned.")

    ranked = sorted(best_by_user.items(), key=lambda item: item[1], reverse=True)
    top_id, top_score = ranked[0]
    if top_score < min_similarity:
        return _reject("best candidate is below the minimum similarity threshold.")
    if len(ranked) > 1 and top_score - ranked[1][1] < min_margin:
        return _reject("another person scores too close to the best match.")

    user = db.session.get(User, top_id)
    if user is None:
        return _reject("matched user does not exist.")
    if user.role != Role.STAFF:
        return _reject("matched account is not a staff account.")
    if not user.is_operational:
        return _reject("matched staff account is not operational.")
    if not idv.has_verified_identity(user):
        return _reject("matched staff account has no verified identity.")
    return user
