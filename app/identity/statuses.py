"""Verification status model.

Pure Python on purpose (no Flask, no database) so the rules that decide whether a person is
"verified" can be unit-tested in isolation and read in one place.
"""
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Iterable, Optional


class IdvStatus:
    NOT_STARTED = "not_started"        # no attempt yet (derived: user has no record)
    IN_PROGRESS = "in_progress"        # session created; user is (or may be) in the provider flow
    PENDING_REVIEW = "pending_review"  # provider flagged it for a human reviewer
    ACTION_REQUIRED = "action_required"  # user must do something: resubmit / restart / re-verify
    VERIFIED = "verified"              # provider approved
    REJECTED = "rejected"              # provider declined (an actual verification failure)
    ERROR = "error"                    # OUR side or the provider's API failed - NOT a verdict on the user

    ALL = (NOT_STARTED, IN_PROGRESS, PENDING_REVIEW, ACTION_REQUIRED, VERIFIED, REJECTED, ERROR)


# Didit session statuses are exact, case-sensitive strings (see Didit "Verification statuses").
PROVIDER_STATUS_MAP = {
    "Not Started": IdvStatus.IN_PROGRESS,     # link created, not opened yet
    "In Progress": IdvStatus.IN_PROGRESS,
    "Awaiting User": IdvStatus.IN_PROGRESS,
    "In Review": IdvStatus.PENDING_REVIEW,
    "Approved": IdvStatus.VERIFIED,
    "Declined": IdvStatus.REJECTED,
    "Resubmitted": IdvStatus.ACTION_REQUIRED,  # reviewer asked the user to redo specific steps
    "Abandoned": IdvStatus.ACTION_REQUIRED,    # user started but did not finish -> restart
    "Expired": IdvStatus.ACTION_REQUIRED,      # link timed out before use -> restart
    "Kyc Expired": IdvStatus.ACTION_REQUIRED,  # a previously approved check aged out -> re-verify
}

# Which status may follow which. A status never moves backwards out of a final verdict, except
# the one documented case (an approved check expiring).
ALLOWED_TRANSITIONS = {
    IdvStatus.NOT_STARTED: {IdvStatus.IN_PROGRESS, IdvStatus.ERROR},
    IdvStatus.IN_PROGRESS: {
        IdvStatus.PENDING_REVIEW, IdvStatus.ACTION_REQUIRED, IdvStatus.VERIFIED,
        IdvStatus.REJECTED, IdvStatus.ERROR,
    },
    IdvStatus.PENDING_REVIEW: {
        IdvStatus.VERIFIED, IdvStatus.REJECTED, IdvStatus.ACTION_REQUIRED,
    },
    IdvStatus.ACTION_REQUIRED: {
        IdvStatus.IN_PROGRESS, IdvStatus.PENDING_REVIEW, IdvStatus.VERIFIED, IdvStatus.REJECTED,
    },
    IdvStatus.VERIFIED: {IdvStatus.ACTION_REQUIRED},  # only via "Kyc Expired"
    IdvStatus.REJECTED: set(),                        # final; a retry is a NEW attempt
    IdvStatus.ERROR: {IdvStatus.IN_PROGRESS},
}

# Outcomes of evaluating an incoming provider status against what we already hold.
APPLIED = "applied"
UNCHANGED = "unchanged"
STALE = "stale"                        # older than what we've already processed
INVALID = "invalid_transition"         # would move a status somewhere it may not go
UNKNOWN = "unknown_status"             # provider sent a status we don't recognise


@dataclass(frozen=True)
class TransitionPlan:
    outcome: str
    new_status: Optional[str] = None


def map_provider_status(provider_status: Optional[str]) -> Optional[str]:
    return PROVIDER_STATUS_MAP.get(provider_status or "")


def can_transition(current: str, new: str) -> bool:
    return current == new or new in ALLOWED_TRANSITIONS.get(current, set())


def plan_transition(
    current: str,
    provider_status: Optional[str],
    event_time: Optional[datetime] = None,
    last_event_time: Optional[datetime] = None,
) -> TransitionPlan:
    """Decide what to do with an incoming provider status. Never guesses on unknown input."""
    new = map_provider_status(provider_status)
    if new is None:
        return TransitionPlan(UNKNOWN)
    if event_time is not None and last_event_time is not None and event_time < last_event_time:
        return TransitionPlan(STALE)
    if new == current:
        return TransitionPlan(UNCHANGED, current)
    if not can_transition(current, new):
        return TransitionPlan(INVALID)
    return TransitionPlan(APPLIED, new)


# --- reading the provider's decision without keeping any personal data ------------------------
_FEATURE_ARRAYS = (
    "id_verifications", "nfc_verifications", "liveness_checks", "face_matches",
    "phone_verifications", "email_verifications", "poa_verifications", "aml_screenings",
    "ip_analyses", "database_validations",
)
_CODE_RE = re.compile(r"^[A-Z0-9_]{2,64}$")


def extract_reason_codes(decision: Optional[dict], limit: int = 10) -> list:
    """Collect machine risk codes (e.g. DOCUMENT_EXPIRED) from per-feature `warnings`.

    Only the code strings are kept: no names, numbers, scores or images.
    """
    codes = []
    if not isinstance(decision, dict):
        return codes
    for key in _FEATURE_ARRAYS:
        for item in decision.get(key) or []:
            if not isinstance(item, dict):
                continue
            for warning in item.get("warnings") or []:
                if not isinstance(warning, dict):
                    continue
                if warning.get("log_type") not in (None, "error", "warning"):
                    continue
                code = warning.get("risk")
                if isinstance(code, str) and _CODE_RE.match(code) and code not in codes:
                    codes.append(code)
                if len(codes) >= limit:
                    return codes
    return codes


def extract_document_type(decision: Optional[dict]) -> Optional[str]:
    """Only the kind of document (e.g. "Passport"), never its number or contents."""
    if not isinstance(decision, dict):
        return None
    for item in decision.get("id_verifications") or []:
        if isinstance(item, dict) and isinstance(item.get("document_type"), str):
            return item["document_type"][:40]
    return None


def reason_category(codes: Iterable[str]) -> str:
    """Collapse raw codes into a coarse, user-safe category.

    Only DOCUMENT_EXPIRED and LOW_FACE_MATCH_SIMILARITY are documented examples from the provider;
    anything unrecognised falls through to "other" rather than being guessed at or shown.
    """
    codes = list(codes or [])
    if any("DOCUMENT" in c and "EXPIRED" in c for c in codes):
        return "document_expired"
    if any(c.startswith(("DOCUMENT", "ID_", "MRZ", "BARCODE")) for c in codes):
        return "document"
    if any(("FACE" in c) or ("LIVENESS" in c) for c in codes):
        return "face"
    return "other"


# --- what we tell the user (deliberately generic: no fraud rules, scores or thresholds) ---------
CATEGORY_HINTS = {
    "document_expired": "The ID you used appears to be expired. Please use a valid, unexpired ID.",
    "document": "We couldn't accept the ID document. Use a clear, undamaged, government-issued ID.",
    "face": "We couldn't confirm the selfie step. Try again in good lighting, facing the camera.",
    "other": "We couldn't complete the check with the information provided.",
}

STATUS_COPY = {
    IdvStatus.NOT_STARTED: {
        "label": "Not verified", "badge": "neutral",
        "headline": "Verify your identity",
        "body": "Confirm who you are with a government-issued ID and a quick selfie.",
        "can_start": True, "start_label": "Start verification",
    },
    IdvStatus.IN_PROGRESS: {
        "label": "In progress", "badge": "info",
        "headline": "Verification in progress",
        "body": "If you haven't finished, continue where you left off. If you just finished, "
                "check your status in a moment.",
        "can_start": True, "start_label": "Continue verification",
    },
    IdvStatus.PENDING_REVIEW: {
        "label": "Under review", "badge": "warn",
        "headline": "We're reviewing your verification",
        "body": "A reviewer is checking your submission. You don't need to do anything. "
                "We'll update this page when there's a result.",
        "can_start": False, "start_label": None,
    },
    IdvStatus.ACTION_REQUIRED: {
        "label": "Action needed", "badge": "warn",
        "headline": "Action needed",
        "body": "Your verification wasn't completed. Please start again to finish it.",
        "can_start": True, "start_label": "Start again",
    },
    IdvStatus.VERIFIED: {
        "label": "Verified", "badge": "success",
        "headline": "Your identity is verified",
        "body": "You're all set. We'll ask you to verify again if your verification expires.",
        "can_start": False, "start_label": None,
    },
    IdvStatus.REJECTED: {
        "label": "Not verified", "badge": "danger",
        "headline": "We couldn't verify your identity",
        "body": "You can try again with a valid ID. If this keeps happening, contact your administrator.",
        "can_start": True, "start_label": "Try again",
    },
    IdvStatus.ERROR: {
        "label": "Temporary problem", "badge": "warn",
        "headline": "Something went wrong on our side",
        "body": "This isn't a problem with your ID. Please try again in a few minutes.",
        "can_start": True, "start_label": "Try again",
    },
}
