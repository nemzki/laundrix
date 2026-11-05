"""The account-status migration on in-memory SQLite, against a minimal pre-migration schema.
(MySQL-specific behaviour still needs one real `flask db upgrade`.)"""
import importlib.util
import pathlib

import pytest

sa = pytest.importorskip("sqlalchemy")
pytest.importorskip("alembic")
from alembic.migration import MigrationContext  # noqa: E402
from alembic.operations import Operations  # noqa: E402

VERSIONS = pathlib.Path(__file__).resolve().parents[2] / "migrations" / "versions"


def _load(rev):
    path = next(VERSIONS.glob(f"{rev}_*.py"))
    spec = importlib.util.spec_from_file_location(f"mig_{rev}", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _run(conn, fn):
    with Operations.context(MigrationContext.configure(conn)):
        fn()


def _cols(conn, table):
    return {c["name"] for c in sa.inspect(conn).get_columns(table)}


@pytest.fixture()
def conn():
    engine = sa.create_engine("sqlite://")
    with engine.begin() as c:
        c.execute(sa.text("CREATE TABLE users (id INTEGER PRIMARY KEY, email VARCHAR(255) NOT NULL UNIQUE, "
                          "role VARCHAR(10) NOT NULL, is_active BOOLEAN NOT NULL)"))
        c.execute(sa.text("CREATE TABLE auth_events (id INTEGER PRIMARY KEY, user_id INTEGER, event VARCHAR(40) NOT NULL)"))
        c.execute(sa.text("INSERT INTO users VALUES (1,'admin@example.com','admin',1),(2,'staff@example.com','staff',1),"
                          "(3,'gone@example.com','staff',0)"))
        c.execute(sa.text("INSERT INTO auth_events VALUES (1, 1, 'login')"))
        yield c


def test_chain_continues_from_the_payments_migration():
    assert _load("e7b3c9a4d1f6").down_revision == "d4e8f1a2b6c7"


def test_existing_users_keep_working_and_disabled_ones_are_labelled(conn):
    _run(conn, _load("e7b3c9a4d1f6").upgrade)
    rows = dict(conn.execute(sa.text("SELECT email, account_status FROM users")).all())
    assert rows == {"admin@example.com": "active", "staff@example.com": "active", "gone@example.com": "deactivated"}
    assert conn.execute(sa.text("SELECT COUNT(*) FROM users WHERE username IS NOT NULL OR password_hash IS NOT NULL")).scalar() == 0
    assert conn.execute(sa.text("SELECT failed_login_attempts FROM users WHERE id = 1")).scalar() == 0
    assert conn.execute(sa.text("SELECT COUNT(*) FROM auth_events")).scalar() == 1            # audit rows untouched
    assert {"target_user_id", "detail"} <= _cols(conn, "auth_events")


def test_constraints_are_enforced_after_upgrade(conn):
    _run(conn, _load("e7b3c9a4d1f6").upgrade)
    with pytest.raises(sa.exc.IntegrityError):
        conn.execute(sa.text("UPDATE users SET account_status = 'superuser' WHERE id = 2"))
    conn.execute(sa.text("UPDATE users SET username = 'boss' WHERE id = 1"))
    with pytest.raises(sa.exc.IntegrityError):
        conn.execute(sa.text("UPDATE users SET username = 'boss' WHERE id = 2"))


def test_downgrade_restores_the_original_shape_and_keeps_rows(conn):
    mod = _load("e7b3c9a4d1f6")
    before_users, before_events = _cols(conn, "users"), _cols(conn, "auth_events")
    _run(conn, mod.upgrade)
    _run(conn, mod.downgrade)
    assert _cols(conn, "users") == before_users and _cols(conn, "auth_events") == before_events
    assert conn.execute(sa.text("SELECT COUNT(*) FROM users")).scalar() == 3
    _run(conn, mod.upgrade)                                                                  # repeatable
    assert "account_status" in _cols(conn, "users")
