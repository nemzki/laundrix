import json
import time
import uuid

import pytest
from flask import g

from app import create_app
from app.extensions import db
from app.identity.signature import compute_signature_v2
from app.models import IdentityVerification, IdentityVerificationEvent, Role, User
from config import TestingConfig
from tests.identity.fakes import FakeProvider

WEBHOOK_SECRET = TestingConfig.DIDIT_WEBHOOK_SECRET


@pytest.fixture()
def app():
    app = create_app(TestingConfig)
    app.config["STAFF_GOOGLE_LOGIN_ALLOWED"] = False
    app.extensions["idv_provider"] = FakeProvider()
    # Tests log in by writing the session directly (there is no password login), so switch off
    # Flask-Login's IP/user-agent session fingerprinting for them.
    app.config["SESSION_PROTECTION"] = None
    app.login_manager.session_protection = None

    # These tests keep ONE app context open (for direct DB access). Flask reuses it for every request,
    # so `g` - where Flask-Login caches the current user - would leak from one test client to the next
    # and make every client act as the first user. In production each request gets its own app context.
    # NOTE: a before_request function must return None, or Flask treats the value as the response.
    def _forget_cached_user():
        g.pop("_login_user", None)

    app.before_request_funcs.setdefault(None, []).insert(0, _forget_cached_user)
    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()


@pytest.fixture()
def provider(app):
    return app.extensions["idv_provider"]


@pytest.fixture()
def make_user(app):
    def _make(email="sam@example.com", role=Role.STAFF, active=True):
        user = User(email=email, role=role, is_active=active)
        db.session.add(user)
        db.session.commit()
        return user
    return _make


def login(client, user):
    with client.session_transaction() as sess:
        sess["_user_id"] = str(user.id)
        sess["_fresh"] = True


@pytest.fixture()
def user(make_user):
    return make_user()


@pytest.fixture()
def client(app, user):
    c = app.test_client()
    login(c, user)
    return c


# ----------------------------------------------------------------------------- helpers
def start(client, consent=True):
    return client.post("/identity/start", data={"consent": "on"} if consent else {})


def latest(user_id):
    db.session.expire_all()
    return db.session.execute(
        db.select(IdentityVerification).filter_by(user_id=user_id).order_by(IdentityVerification.id.desc())
    ).scalars().first()


def event_rows(verification_id):
    db.session.expire_all()
    return db.session.execute(
        db.select(IdentityVerificationEvent).filter_by(verification_id=verification_id)
        .order_by(IdentityVerificationEvent.id)
    ).scalars().all()


def webhook_body(v, status, *, event_id=None, created_at=None, environment="sandbox",
                 decision=None, vendor_data=None, webhook_type="status.updated", session_id=None):
    now = int(time.time())
    body = {
        "event_id": event_id or str(uuid.uuid4()),
        "webhook_type": webhook_type,
        "timestamp": now,
        "created_at": created_at if created_at is not None else now,
        "environment": environment,
        "session_id": session_id or v.provider_session_id,
        "status": status,
        "vendor_data": vendor_data if vendor_data is not None else f"laundrix:{v.user_id}",
    }
    if decision is not None:
        body["decision"] = decision
    return body


def post_webhook(client, body, *, secret=WEBHOOK_SECRET, signature=None, timestamp=None,
                 headers=None, raw=None):
    h = {
        "X-Signature-V2": signature if signature is not None else compute_signature_v2(body, secret),
        "X-Timestamp": str(int(time.time())) if timestamp is None else timestamp,
    }
    h.update(headers or {})
    return client.post(
        "/identity/webhook/didit",
        data=raw if raw is not None else json.dumps(body),
        content_type="application/json", headers=h,
    )


def warning(code):
    return {"risk": code, "log_type": "error"}
