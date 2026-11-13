
"""Tests for the staff Face Login endpoint."""

import io
import uuid

from app.extensions import db
from app.models import AuthEvent, IdentityVerification, User
from app.models.staff_credential import utcnow
from app.staff_auth.services import create_staff
from config import TestingConfig
from tests.laundry.conftest import _make_app
from tests.staffmgmt.conftest import app


def make_verified_staff():
    user, _sid, _token = create_staff(
        "face@example.com",
        "Face Test",
    )
    db.session.add(
        IdentityVerification(
            user_id=user.id,
            provider="didit",
            provider_session_id=str(uuid.uuid4()),
            environment="sandbox",
            status="verified",
            purpose="kyc",
            decided_at=utcnow(),
            completed_at=utcnow(),
        )
    )
    db.session.commit()
    return user


def upload_image(filename="capture.jpg", content=b"fake-image-data"):
    return {
        "image": (io.BytesIO(content), filename),
    }


def signed_in(client):
    with client.session_transaction() as sess:
        return "_user_id" in sess


def test_face_login_success_establishes_staff_session(app, monkeypatch):
    user = make_verified_staff()
    original_failures = user.failed_login_attempts

    def fake_authenticate(image_bytes, *, filename):
        assert image_bytes == b"fake-image-data"
        assert filename == "capture.jpg"
        return user

    monkeypatch.setattr(
        "app.auth.routes.authenticate_with_face",
        fake_authenticate,
    )

    client = app.test_client()
    response = client.post(
        "/auth/face-login",
        data=upload_image(),
        content_type="multipart/form-data",
    )

    assert response.status_code == 200
    assert response.json["ok"] is True
    assert response.json["redirect_url"].endswith("/dashboard/staff")
    assert signed_in(client)

    db.session.expire_all()
    refreshed = db.session.get(User, user.id)

    assert refreshed.last_login_at is not None
    assert refreshed.failed_login_attempts == original_failures

    events = db.session.scalars(
        db.select(AuthEvent).filter_by(
            event="face_login_success",
            user_id=user.id,
            target_user_id=user.id,
        )
    ).all()

    assert len(events) == 1


def test_face_login_rejects_unmatched_face_without_session(app, monkeypatch):
    monkeypatch.setattr(
        "app.auth.routes.authenticate_with_face",
        lambda *args, **kwargs: None,
    )

    client = app.test_client()
    response = client.post(
        "/auth/face-login",
        data=upload_image(),
        content_type="multipart/form-data",
    )

    assert response.status_code == 401
    assert response.json["ok"] is False
    assert not signed_in(client)


def test_face_login_rejects_missing_image(app, monkeypatch):
    called = False

    def fake_authenticate(*args, **kwargs):
        nonlocal called
        called = True

    monkeypatch.setattr(
        "app.auth.routes.authenticate_with_face",
        fake_authenticate,
    )

    response = app.test_client().post("/auth/face-login")

    assert response.status_code == 400
    assert not called


def test_face_login_rejects_unsupported_file_extension(app, monkeypatch):
    called = False

    def fake_authenticate(*args, **kwargs):
        nonlocal called
        called = True

    monkeypatch.setattr(
        "app.auth.routes.authenticate_with_face",
        fake_authenticate,
    )

    response = app.test_client().post(
        "/auth/face-login",
        data=upload_image(filename="capture.gif"),
        content_type="multipart/form-data",
    )

    assert response.status_code == 400
    assert not called


def test_face_login_rejects_oversized_image(app, monkeypatch):
    called = False

    def fake_authenticate(*args, **kwargs):
        nonlocal called
        called = True

    monkeypatch.setattr(
        "app.auth.routes.authenticate_with_face",
        fake_authenticate,
    )

    oversized = b"x" * (1400 * 1024 + 1)

    response = app.test_client().post(
        "/auth/face-login",
        data=upload_image(content=oversized),
        content_type="multipart/form-data",
    )

    assert response.status_code == 413
    assert not called


def test_face_login_handles_provider_failure(app, monkeypatch):
    from app.identity.provider.base import ProviderUnavailable

    def fail(*args, **kwargs):
        raise ProviderUnavailable("private provider detail")

    monkeypatch.setattr(
        "app.auth.routes.authenticate_with_face",
        fail,
    )

    response = app.test_client().post(
        "/auth/face-login",
        data=upload_image(),
        content_type="multipart/form-data",
    )

    assert response.status_code == 503
    assert response.json["ok"] is False
    assert b"private provider detail" not in response.data


def test_face_login_is_disabled_when_identity_verification_is_disabled(
    app, monkeypatch
):
    app.config["IDV_ENABLED"] = False

    called = False

    def fake_authenticate(*args, **kwargs):
        nonlocal called
        called = True

    monkeypatch.setattr(
        "app.auth.routes.authenticate_with_face",
        fake_authenticate,
    )

    response = app.test_client().post(
        "/auth/face-login",
        data=upload_image(),
        content_type="multipart/form-data",
    )

    assert response.status_code == 404
    assert not called


def test_face_login_enforces_csrf():
    class CsrfOn(TestingConfig):
        WTF_CSRF_ENABLED = True

    app = _make_app(CsrfOn)

    with app.app_context():
        db.create_all()

        response = app.test_client().post(
            "/auth/face-login",
            data=upload_image(),
            content_type="multipart/form-data",
        )

        assert response.status_code == 400

        db.session.remove()
        db.drop_all()


def test_authenticated_admin_cannot_use_face_login(
    app, admin_client, monkeypatch
):
    called = False

    def fake_authenticate(*args, **kwargs):
        nonlocal called
        called = True

    monkeypatch.setattr(
        "app.auth.routes.authenticate_with_face",
        fake_authenticate,
    )

    response = admin_client.post(
        "/auth/face-login",
        data=upload_image(),
        content_type="multipart/form-data",
    )

    assert response.status_code == 409
    assert not called

    with admin_client.session_transaction() as sess:
        assert sess.get("_user_id") is not None


def test_face_login_clears_session_when_audit_commit_fails(
    app, monkeypatch
):
    from sqlalchemy.exc import SQLAlchemyError

    user = make_verified_staff()

    monkeypatch.setattr(
        "app.auth.routes.authenticate_with_face",
        lambda *args, **kwargs: user,
    )

    def fail_commit():
        raise SQLAlchemyError("simulated database failure")

    monkeypatch.setattr(db.session, "commit", fail_commit)

    client = app.test_client()

    response = client.post(
        "/auth/face-login",
        data=upload_image(),
        content_type="multipart/form-data",
    )

    assert response.status_code == 500
    assert response.json["ok"] is False
    assert not signed_in(client)
