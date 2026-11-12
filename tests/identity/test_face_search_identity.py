
import uuid

import pytest

from app.extensions import db
from app.identity import services as idv
from app.models import IdentityVerification, Role, User
from app.models.user import AccountStatus
from app.models.staff_credential import utcnow


FACE_MATCH_MIN_SIMILARITY = 90.0


@pytest.fixture()
def enrolled_staff(app):
    user = User(
        email=f"face-test-{uuid.uuid4().hex[:8]}@example.com",
        role=Role.STAFF,
        is_active=True,
        account_status=AccountStatus.ACTIVE,
    )
    db.session.add(user)
    db.session.flush()

    db.session.add(IdentityVerification(
        user_id=user.id,
        provider="didit",
        provider_session_id=str(uuid.uuid4()),
        environment="sandbox",
        status="verified",
        purpose=idv.PURPOSE_KYC,
        decided_at=utcnow(),
        completed_at=utcnow(),
    ))
    db.session.commit()

    return user


def make_report(user_id, score=95.0, **overrides):
    match = {
        "vendor_data": f"laundrix:{user_id}",
        "similarity_percentage": score,
        "status": "Approved",
        "is_blocklisted": False,
    }
    match.update(overrides)

    return {
        "face_search": {
            "status": "Approved",
            "total_matches": 1,
            "matches": [match],
        }
    }


def test_resolves_one_valid_enrolled_staff_match(app, enrolled_staff):
    from app.identity.face_search import resolve_face_search_identity

    result = resolve_face_search_identity(make_report(enrolled_staff.id))

    assert result is not None
    assert result.id == enrolled_staff.id


def test_rejects_match_below_minimum_similarity(app, enrolled_staff):
    from app.identity.face_search import resolve_face_search_identity

    report = make_report(
        enrolled_staff.id,
        score=FACE_MATCH_MIN_SIMILARITY - 0.1,
    )

    assert resolve_face_search_identity(report) is None


def test_accepts_match_at_minimum_similarity(app, enrolled_staff):
    from app.identity.face_search import resolve_face_search_identity

    report = make_report(
        enrolled_staff.id,
        score=FACE_MATCH_MIN_SIMILARITY,
    )

    result = resolve_face_search_identity(report)

    assert result is not None
    assert result.id == enrolled_staff.id


@pytest.mark.parametrize("vendor_data", [
    None,
    "",
    "42",
    "laundrix:0",
    "laundrix:-1",
    "laundrix:not-a-number",
    "other-system:42",
])
def test_rejects_missing_or_malformed_vendor_data(app, enrolled_staff, vendor_data):
    from app.identity.face_search import resolve_face_search_identity

    report = make_report(enrolled_staff.id, vendor_data=vendor_data)

    assert resolve_face_search_identity(report) is None


def test_rejects_blocklisted_match(app, enrolled_staff):
    from app.identity.face_search import resolve_face_search_identity

    report = make_report(enrolled_staff.id, is_blocklisted=True)

    assert resolve_face_search_identity(report) is None


def test_rejects_non_approved_match(app, enrolled_staff):
    from app.identity.face_search import resolve_face_search_identity

    report = make_report(enrolled_staff.id, status="Declined")

    assert resolve_face_search_identity(report) is None


def test_rejects_user_that_does_not_exist(app):
    from app.identity.face_search import resolve_face_search_identity

    report = make_report(999999999)

    assert resolve_face_search_identity(report) is None


def test_rejects_admin_account(app):
    from app.identity.face_search import resolve_face_search_identity

    admin = User(
        email="face-admin@example.com",
        role=Role.ADMIN,
        is_active=True,
        account_status=AccountStatus.ACTIVE,
    )
    db.session.add(admin)
    db.session.flush()

    db.session.add(IdentityVerification(
        user_id=admin.id,
        provider="didit",
        provider_session_id=str(uuid.uuid4()),
        environment="sandbox",
        status="verified",
        purpose=idv.PURPOSE_KYC,
        decided_at=utcnow(),
        completed_at=utcnow(),
    ))
    db.session.commit()

    assert resolve_face_search_identity(make_report(admin.id)) is None


@pytest.mark.parametrize("status", [
    AccountStatus.PENDING_VERIFICATION,
    AccountStatus.PENDING_APPROVAL,
    AccountStatus.SUSPENDED,
    AccountStatus.DEACTIVATED,
    AccountStatus.REJECTED,
])
def test_rejects_non_operational_staff_account(app, enrolled_staff, status):
    from app.identity.face_search import resolve_face_search_identity

    enrolled_staff.account_status = status
    db.session.commit()

    assert resolve_face_search_identity(
        make_report(enrolled_staff.id)
    ) is None


def test_rejects_inactive_staff_account(app, enrolled_staff):
    from app.identity.face_search import resolve_face_search_identity

    enrolled_staff.is_active = False
    db.session.commit()

    assert resolve_face_search_identity(
        make_report(enrolled_staff.id)
    ) is None


def test_rejects_staff_without_verified_kyc(app):
    from app.identity.face_search import resolve_face_search_identity

    user = User(
        email="unverified@example.com",
        role=Role.STAFF,
        is_active=True,
        account_status=AccountStatus.ACTIVE,
    )
    db.session.add(user)
    db.session.commit()

    assert resolve_face_search_identity(
        make_report(user.id)
    ) is None


def test_rejects_empty_matches(app):
    from app.identity.face_search import resolve_face_search_identity

    report = {
        "face_search": {
            "status": "Approved",
            "total_matches": 0,
            "matches": [],
        }
    }

    assert resolve_face_search_identity(report) is None


def test_rejects_multiple_matches(app, enrolled_staff):
    from app.identity.face_search import resolve_face_search_identity

    report = make_report(enrolled_staff.id)
    report["face_search"]["matches"].append({
        "vendor_data": "laundrix:999999",
        "similarity_percentage": 94.0,
        "status": "Approved",
        "is_blocklisted": False,
    })
    report["face_search"]["total_matches"] = 2

    assert resolve_face_search_identity(report) is None


@pytest.mark.parametrize("report", [
    None,
    {},
    [],
    {"face_search": None},
    {"face_search": {"matches": "invalid"}},
    {"face_search": {"matches": [{}]}},
])
def test_rejects_malformed_provider_response(app, report):
    from app.identity.face_search import resolve_face_search_identity

    assert resolve_face_search_identity(report) is None


def test_rejects_inconsistent_match_count(app, enrolled_staff):
    from app.identity.face_search import resolve_face_search_identity

    report = make_report(enrolled_staff.id)
    report["face_search"]["total_matches"] = 2

    assert resolve_face_search_identity(report) is None


def test_rejects_conflicting_top_level_and_nested_matches(app, enrolled_staff):
    from app.identity.face_search import resolve_face_search_identity

    report = make_report(enrolled_staff.id)
    report["matches"] = [{
        "vendor_data": "laundrix:999999",
        "similarity_percentage": 99.0,
        "status": "Approved",
        "is_blocklisted": False,
    }]

    assert resolve_face_search_identity(report) is None

def test_accepts_top_level_response_with_fractional_similarity_score(
    app, enrolled_staff
):
    from app.identity.face_search import resolve_face_search_identity

    report = {
        "status": "Approved",
        "total_matches": 1,
        "matches": [{
            "vendor_data": f"laundrix:{enrolled_staff.id}",
            "similarity_score": 0.95,
            "status": "Approved",
            "is_blocklisted": False,
        }],
    }

    result = resolve_face_search_identity(report)

    assert result is not None
    assert result.id == enrolled_staff.id


def test_accepts_fractional_similarity_score_at_threshold(
    app, enrolled_staff
):
    from app.identity.face_search import resolve_face_search_identity

    report = {
        "status": "Approved",
        "total_matches": 1,
        "matches": [{
            "vendor_data": f"laundrix:{enrolled_staff.id}",
            "similarity_score": 0.90,
            "status": "Approved",
            "is_blocklisted": False,
        }],
    }

    result = resolve_face_search_identity(report)

    assert result is not None
    assert result.id == enrolled_staff.id


def test_rejects_conflicting_top_level_status(
    app, enrolled_staff
):
    from app.identity.face_search import resolve_face_search_identity

    report = make_report(enrolled_staff.id)
    report["status"] = "Declined"

    assert resolve_face_search_identity(report) is None