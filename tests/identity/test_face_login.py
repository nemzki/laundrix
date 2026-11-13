
from unittest.mock import Mock, call

from app.identity import face_login


def test_face_search_runs_only_after_approved_passive_liveness(monkeypatch):
    provider = Mock()
    provider.passive_liveness.return_value = {
        "liveness": {
            "status": "Approved",
            "method": "PASSIVE",
        }
    }
    provider.face_search.return_value = {"matches": []}

    resolved_user = object()
    get_provider = Mock(return_value=provider)
    resolve_identity = Mock(return_value=resolved_user)

    monkeypatch.setattr(face_login, "get_idv_provider", get_provider)
    monkeypatch.setattr(
        face_login,
        "resolve_face_search_identity",
        resolve_identity,
    )

    image = b"test-image"

    result = face_login.authenticate_with_face(
        image,
        filename="capture.jpg",
    )

    assert result is resolved_user
    assert provider.method_calls == [
        call.passive_liveness(image, filename="capture.jpg"),
        call.face_search(
            image,
            filename="capture.jpg",
            similarity_threshold=90,
            allow_multiple_faces=False,
        ),
    ]
    resolve_identity.assert_called_once_with({"matches": []})


def test_face_search_is_not_called_when_liveness_is_rejected(monkeypatch):
    provider = Mock()
    provider.passive_liveness.return_value = {
        "liveness": {
            "status": "Declined",
            "method": "PASSIVE",
        }
    }

    monkeypatch.setattr(
        face_login,
        "get_idv_provider",
        Mock(return_value=provider),
    )

    result = face_login.authenticate_with_face(b"test-image")

    assert result is None
    provider.face_search.assert_not_called()


def test_face_search_is_not_called_for_malformed_liveness_report(monkeypatch):
    provider = Mock()
    provider.passive_liveness.return_value = {
        "status": "Approved",
        "method": "PASSIVE",
    }

    monkeypatch.setattr(
        face_login,
        "get_idv_provider",
        Mock(return_value=provider),
    )

    result = face_login.authenticate_with_face(b"test-image")

    assert result is None
    provider.face_search.assert_not_called()


def test_unmatched_face_returns_none(monkeypatch):
    provider = Mock()
    provider.passive_liveness.return_value = {
        "liveness": {
            "status": "Approved",
            "method": "PASSIVE",
        }
    }
    provider.face_search.return_value = {"matches": []}

    monkeypatch.setattr(
        face_login,
        "get_idv_provider",
        Mock(return_value=provider),
    )
    monkeypatch.setattr(
        face_login,
        "resolve_face_search_identity",
        Mock(return_value=None),
    )

    result = face_login.authenticate_with_face(b"test-image")

    assert result is None
    provider.face_search.assert_called_once()
