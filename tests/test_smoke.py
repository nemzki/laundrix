import pytest

from app import create_app
from app.extensions import db
from config import TestingConfig


@pytest.fixture()
def client():
    app = create_app(TestingConfig)
    with app.app_context():
        db.create_all()
        yield app.test_client()
        db.drop_all()


def test_landing_page(client):
    assert client.get("/").status_code == 200


def test_login_page(client):
    assert client.get("/auth/login").status_code == 200


def test_dashboard_requires_login(client):
    r = client.get("/dashboard/")
    assert r.status_code == 302 and "/auth/login" in r.headers["Location"]


def test_unknown_page_404(client):
    assert client.get("/nope").status_code == 404
