"""The payments migration, run on in-memory SQLite against a minimal pre-payment schema.
(MySQL-specific behaviour still needs one real `flask db upgrade`; see README.)"""
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


@pytest.fixture()
def conn():
    engine = sa.create_engine("sqlite://")
    with engine.begin() as c:
        c.execute(sa.text("CREATE TABLE users (id INTEGER PRIMARY KEY, email VARCHAR(255))"))
        c.execute(sa.text(
            "CREATE TABLE orders (id INTEGER PRIMARY KEY, reference VARCHAR(24) NOT NULL, "
            "total NUMERIC(10,2) NOT NULL, created_at DATETIME NOT NULL)"
        ))
        c.execute(sa.text("INSERT INTO users (id, email) VALUES (1, 'a@example.com')"))
        c.execute(sa.text(
            "INSERT INTO orders (id, reference, total, created_at) "
            "VALUES (1, 'LX-OLD-1', 160.00, '2026-10-01 08:30:00'), (2, 'LX-OLD-2', 80.00, '2026-10-02 09:00:00')"
        ))
        yield c


def _cols(conn, table):
    return {c["name"] for c in sa.inspect(conn).get_columns(table)}


def test_revision_chain_continues_from_the_tracking_migration():
    mod = _load("d4e8f1a2b6c7")
    assert mod.down_revision == "fbc865bc8499"


def test_existing_orders_survive_and_are_marked_untracked_but_received(conn):
    mod = _load("d4e8f1a2b6c7")
    _run(conn, mod.upgrade)
    rows = conn.execute(sa.text(
        "SELECT reference, total, payment_arrangement, received_at, received_by_id, submission_token "
        "FROM orders ORDER BY id")).all()
    assert [r[0] for r in rows] == ["LX-OLD-1", "LX-OLD-2"]
    assert [float(r[1]) for r in rows] == [160.0, 80.0]
    assert all(r[2] is None for r in rows)                # "Payment not tracked"
    assert rows[0][3] == "2026-10-01 08:30:00" or str(rows[0][3]).startswith("2026-10-01 08:30")  # back-filled
    assert all(r[4] is None and r[5] is None for r in rows)
    assert {"payment_methods", "payment_settings", "payments", "payment_events"} <= set(sa.inspect(conn).get_table_names())


def test_payments_table_enforces_its_constraints(conn):
    _run(conn, _load("d4e8f1a2b6c7").upgrade)
    conn.execute(sa.text("INSERT INTO payment_methods (id, code, label, is_active, requires_reference, sort_order, created_at, updated_at) "
                         "VALUES (1, 'cash', 'Cash', 1, 0, 10, '2026-11-01', '2026-11-01')"))
    ins = ("INSERT INTO payments (order_id, kind, method_id, method_code, method_label, amount, paid_at, created_at, "
           "reverses_payment_id, idempotency_key) VALUES (1, :kind, 1, 'cash', 'Cash', :amt, '2026-11-01', '2026-11-01', :rev, :key)")
    conn.execute(sa.text(ins), {"kind": "payment", "amt": 100, "rev": None, "key": "k1"})
    for params in (
        {"kind": "payment", "amt": 0, "rev": None, "key": "k2"},       # amount must be positive
        {"kind": "payment", "amt": -5, "rev": None, "key": "k3"},
        {"kind": "reversal", "amt": 100, "rev": None, "key": "k4"},    # reversal must point at a payment
        {"kind": "payment", "amt": 10, "rev": 1, "key": "k5"},         # payment must not point at one
        {"kind": "payment", "amt": 10, "rev": None, "key": "k1"},      # duplicate idempotency key
    ):
        with pytest.raises(sa.exc.IntegrityError):   # SQLite rolls back just the failed statement
            conn.execute(sa.text(ins), params)
    conn.execute(sa.text(ins), {"kind": "reversal", "amt": 100, "rev": 1, "key": None})
    with pytest.raises(sa.exc.IntegrityError):       # a payment can be reversed only once
        conn.execute(sa.text(ins), {"kind": "reversal", "amt": 100, "rev": 1, "key": None})


def test_downgrade_restores_the_original_orders_shape_and_rows(conn):
    mod = _load("d4e8f1a2b6c7")
    before = _cols(conn, "orders")
    _run(conn, mod.upgrade)
    assert {"payment_arrangement", "received_at", "received_by_id", "submission_token"} <= _cols(conn, "orders")
    _run(conn, mod.downgrade)
    assert _cols(conn, "orders") == before
    assert conn.execute(sa.text("SELECT COUNT(*) FROM orders")).scalar() == 2
    assert not ({"payments", "payment_events", "payment_methods", "payment_settings"} & set(sa.inspect(conn).get_table_names()))
    _run(conn, mod.upgrade)         # repeatable
    assert "received_at" in _cols(conn, "orders")
