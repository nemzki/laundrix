import pytest

from app.extensions import db
from app.models import AccountStatus, Role, User
from config import TestingConfig
from tests.identity.fakes import FakeProvider
from tests.laundry.conftest import _login, _make_app


@pytest.fixture()
def app():
    app = _make_app(TestingConfig)
    app.config["STAFF_GOOGLE_LOGIN_ALLOWED"] = False
    app.extensions["idv_provider"] = FakeProvider()          # scripted stand-in for Didit (tests only)
    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()


@pytest.fixture()
def make_user(app):
    def _make(email, role=Role.STAFF, status=AccountStatus.ACTIVE, active=True, **extra):
        user = User(email=email, role=role, is_active=active, account_status=status,
                    full_name=email.split("@")[0].title(), **extra)
        db.session.add(user)
        db.session.commit()
        return user
    return _make


@pytest.fixture()
def client_for(app):
    def _client(user):
        c = app.test_client()
        _login(c, user)
        return c
    return _client


GOOD_PASSWORD = "Correct-Horse-Battery-9"

@pytest.fixture()
def provider(app):
    return app.extensions["idv_provider"]


@pytest.fixture()
def admin(make_user):
    return make_user("boss@example.com", role=Role.ADMIN)


@pytest.fixture()
def admin_client(client_for, admin):
    return client_for(admin)


STAFF_PASSWORD = "NewSecurePassword123!"
