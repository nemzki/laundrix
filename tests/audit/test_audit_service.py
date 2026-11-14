"""Audit record creation, sanitising and the append-only guarantee."""
import pytest

from app.audit import services as audit
from app.extensions import db
from app.models import AuditLog, AuditLogImmutableError


def rows():
    return db.session.scalars(db.select(AuditLog).order_by(AuditLog.id)).all()


def test_record_stores_actor_snapshot_and_changes(app, admin):
    audit.record("update", "customers", "Updated customer Ana", actor=admin, resource_id=7,
                 resource_label="Customer Ana", old={"name": "Ann"}, new={"name": "Ana"})
    db.session.commit()
    row = rows()[0]
    assert (row.actor_id, row.actor_name, row.actor_role) == (admin.id, admin.full_name, "admin")
    assert (row.action, row.module, row.resource_id, row.success) == ("update", "customers", "7", True)
    assert row.old_values == {"name": "Ann"} and row.new_values == {"name": "Ana"}
    assert row.created_at is not None


def test_actor_defaults_to_system_without_a_request(app):
    audit.record("create", "accounts", "Created from CLI")
    db.session.commit()
    assert rows()[0].actor_name == "System" and rows()[0].actor_id is None


def test_unknown_action_module_or_empty_description_is_rejected(app):
    for args in (("nope", "orders", "x"), ("update", "nope", "x"), ("update", "orders", "   ")):
        with pytest.raises(ValueError):
            audit.record(*args)


def test_sensitive_keys_are_never_stored(app):
    audit.record("update", "accounts", "x", new={
        "password": "p", "password_hash": "h", "api_key": "k", "access_token": "t", "session_id": "s",
        "csrf_token": "c", "client_secret": "s", "otp": "1", "face_embedding": "e", "full_name": "Sam"})
    db.session.commit()
    assert rows()[0].new_values == {"full_name": "Sam"}


def test_phone_and_email_are_masked_and_long_text_truncated(app):
    audit.record("update", "customers", "x", new={
        "contact_number": "0917 123 4567", "email": "sam@example.com", "notes": "x" * 500})
    db.session.commit()
    v = rows()[0].new_values
    assert v["contact_number"] == "\u2022\u2022\u2022\u20224567" and "917" not in v["contact_number"]
    assert v["email"] == "s***@example.com"
    assert len(v["notes"]) == 200


def test_changes_keeps_only_modified_fields(app):
    old, new = audit.changes({"price": "10", "name": "A"}, {"price": "12", "name": "A"})
    assert old == {"price": "10"} and new == {"price": "12"}
    assert audit.changes({"a": 1}, {"a": 1}) == (None, None)


def test_audit_rows_cannot_be_updated_or_deleted(app):
    audit.record("create", "orders", "x")
    db.session.commit()
    row = rows()[0]
    row.description = "tampered"
    with pytest.raises(AuditLogImmutableError):
        db.session.commit()
    db.session.rollback()
    db.session.delete(db.session.get(AuditLog, row.id))
    with pytest.raises(AuditLogImmutableError):
        db.session.commit()
    db.session.rollback()
    assert db.session.get(AuditLog, row.id).description == "x"
