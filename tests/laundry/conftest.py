import pytest
from flask import g

from app import create_app
from app.catalog.seed import seed_catalog
from app.extensions import db
from app.models import Role, Service, User
from config import TestingConfig


def _make_app(config):
    app = create_app(config)
    app.config["SESSION_PROTECTION"] = None
    app.login_manager.session_protection = None

    def _forget_cached_user():  # one app context is kept open; don't leak Flask-Login's cached user
        g.pop("_login_user", None)

    app.before_request_funcs.setdefault(None, []).insert(0, _forget_cached_user)
    return app


@pytest.fixture()
def app():
    app = _make_app(TestingConfig)
    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()


def _login(client, user):
    with client.session_transaction() as sess:
        sess["_user_id"] = str(user.id)
        sess["_fresh"] = True


def _user(email, role):
    u = User(email=email, role=role, is_active=True, full_name=email.split("@")[0].title())
    db.session.add(u)
    db.session.commit()
    return u


@pytest.fixture()
def admin(app):
    return _user("admin@example.com", Role.ADMIN)


@pytest.fixture()
def staff(app):
    return _user("staff@example.com", Role.STAFF)


@pytest.fixture()
def admin_client(app, admin):
    c = app.test_client()
    _login(c, admin)
    return c


@pytest.fixture()
def staff_client(app, staff):
    c = app.test_client()
    _login(c, staff)
    return c


@pytest.fixture()
def anon_client(app):
    return app.test_client()


@pytest.fixture()
def catalog(app):
    """Confirmed catalog, with billing units configured as an Admin would (the seed leaves them unset)."""
    seed_catalog()
    units = {"wash": "load", "dry": "load", "fold": "kg", "spin": "load"}
    for code, unit in units.items():
        db.session.execute(db.select(Service).filter_by(code=code)).scalar_one().pricing_unit = unit
    db.session.commit()


def svc(code):
    return db.session.execute(db.select(Service).filter_by(code=code)).scalar_one()


NEW_CUSTOMER = {"new": {"full_name": "Ana Cruz", "contact_number": "0917 123 4567"}}
