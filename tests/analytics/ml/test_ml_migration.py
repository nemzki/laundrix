"""The analytics_model_runs migration: additive, constrained, reversible, and in step with the model."""
import importlib.util
import re
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

ROOT = Path(__file__).resolve().parents[3]
REV, PARENT = "a9c4e2d7b1f5", "f2b7d4c9a1e3"


def load(rev):
    path = next((ROOT / "migrations" / "versions").glob(f"{rev}_*.py"))
    spec = importlib.util.spec_from_file_location(f"mig_{rev}", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def run(conn, fn):
    with Operations.context(MigrationContext.configure(conn)):
        fn()


@pytest.fixture()
def conn():
    engine = sa.create_engine("sqlite://")
    with engine.begin() as c:
        c.execute(sa.text("CREATE TABLE orders (id INTEGER PRIMARY KEY, reference VARCHAR(24) NOT NULL)"))
        c.execute(sa.text("INSERT INTO orders VALUES (1, 'LX-OLD-1'), (2, 'LX-OLD-2')"))
        yield c


def insert(conn, **kw):
    row = dict(target="orders", granularity="day", entity="", version=1, status="trained", is_active=0,
               schema_version=1, started_at="2026-11-11 04:00:00")
    row.update(kw)
    conn.execute(sa.text("INSERT INTO analytics_model_runs (target, granularity, entity, version, status, is_active, schema_version, started_at) "
                         "VALUES (:target, :granularity, :entity, :version, :status, :is_active, :schema_version, :started_at)"), row)


def test_migration_chains_from_the_previous_head_and_is_now_the_single_head():
    graph = {}
    for path in (ROOT / "migrations" / "versions").glob("*.py"):
        text = path.read_text(encoding="utf-8")
        rev = re.search(r"^revision\s*=\s*['\"](\w+)['\"]", text, re.M).group(1)
        down = re.search(r"^down_revision\s*=\s*(?:None|['\"](\w+)['\"])", text, re.M).group(1)
        graph[rev] = down
    assert [r for r in graph if r not in graph.values()] == [REV]
    assert graph[REV] == PARENT and graph[PARENT] == "e7b3c9a4d1f6"


def test_upgrade_creates_only_the_new_table_and_leaves_existing_data_alone(conn):
    run(conn, load(REV).upgrade)
    insp = sa.inspect(conn)
    assert set(insp.get_table_names()) == {"orders", "analytics_model_runs"}
    assert conn.execute(sa.text("SELECT COUNT(*) FROM orders")).scalar() == 2
    cols = {c["name"]: c for c in insp.get_columns("analytics_model_runs")}
    assert set(cols) == {"id", "target", "granularity", "entity", "version", "status", "is_active", "algorithm", "kind", "params",
                         "feature_config", "metrics", "schema_version", "checksum", "data_start", "data_end", "n_observations",
                         "n_events", "message", "trained_by", "started_at", "finished_at"}
    assert not any(k in cols for k in ("customer_id", "order_id", "payment_id", "user_id"))      # no personal or transactional links
    assert [i["name"] for i in insp.get_indexes("analytics_model_runs")] == ["ix_analytics_model_runs_key_active"]


def test_constraints_reject_bad_rows(conn):
    run(conn, load(REV).upgrade)
    insert(conn)                                                                  # a valid row
    assert conn.execute(sa.text("SELECT entity FROM analytics_model_runs")).scalar() == ""
    for bad in ({"granularity": "hour"}, {"status": "done"}, {"version": 0}, {"is_active": 1, "status": "error"},
                {"is_active": 1, "status": "evaluation_failed"}, {"is_active": 1, "status": "training"}):
        with pytest.raises(sa.exc.IntegrityError):
            with conn.begin_nested():
                insert(conn, **{"version": 2, **bad})
    with pytest.raises(sa.exc.IntegrityError):                                    # (target, granularity, entity, version) is unique
        with conn.begin_nested():
            insert(conn)
    insert(conn, version=2, is_active=1, status="trained")                         # an active trained run is fine
    insert(conn, entity="service:7")                                               # another entity may reuse version 1


def test_downgrade_removes_only_the_new_table(conn):
    mod = load(REV)
    run(conn, mod.upgrade)
    run(conn, mod.downgrade)
    assert sa.inspect(conn).get_table_names() == ["orders"]
    assert conn.execute(sa.text("SELECT COUNT(*) FROM orders")).scalar() == 2


def test_the_model_and_the_migration_agree(conn):
    from app.models import AnalyticsModelRun
    run(conn, load(REV).upgrade)
    insp = sa.inspect(conn)
    migrated = {c["name"]: c["nullable"] for c in insp.get_columns("analytics_model_runs")}
    model = {c.name: c.nullable for c in AnalyticsModelRun.__table__.columns}
    assert migrated == model
    assert {c["name"] for c in insp.get_check_constraints("analytics_model_runs")} == \
           {c.name for c in AnalyticsModelRun.__table__.constraints if isinstance(c, sa.CheckConstraint)}
    assert {u["name"] for u in insp.get_unique_constraints("analytics_model_runs")} == \
           {c.name for c in AnalyticsModelRun.__table__.constraints if isinstance(c, sa.UniqueConstraint)}
