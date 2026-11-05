"""Migrations: the real chain (users -> staff portal -> identity -> Didit replaces Rekognition),
run on in-memory SQLite so it works anywhere, plus a check that the hand-written ones match the models.

MySQL-specific behaviour (e.g. the JSON column) should still be checked once with a real
`flask db upgrade` against laundrix_db.
"""
import importlib.util
import pathlib

import pytest

sa = pytest.importorskip("sqlalchemy")
pytest.importorskip("alembic")
from alembic.migration import MigrationContext  # noqa: E402
from alembic.operations import Operations  # noqa: E402

VERSIONS = pathlib.Path(__file__).resolve().parents[2] / "migrations" / "versions"
CHAIN = [
    "6aa6497527d1",
    "4b1d2288b22d",
    "c7f3a91d5e20",
    "e1a4b7c92f30",
    "11b2bcbca728",
]
IDENTITY_TABLES = {"identity_verifications", "identity_verification_events"}
# Later revisions that change the tables compared in test_the_full_chain_matches_the_models.
# The revisions between CHAIN and these (orders/payments) never touch those tables, and the order
# tracking migration is MySQL-only, so they are not replayed on SQLite here. The guard test
# test_skipped_revisions_do_not_touch_the_compared_tables enforces that assumption.
LATER_REVISIONS_ON_COMPARED_TABLES = ["e7b3c9a4d1f6"]
FACE_COLUMNS = {"face_id", "face_enrolled_at", "biometric_consent_at"}


def _load(rev):
    path = next(VERSIONS.glob(f"{rev}_*.py"))
    spec = importlib.util.spec_from_file_location(f"mig_{rev}", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _run(conn, fn):
    with Operations.context(MigrationContext.configure(conn)):
        fn()


def _upgrade(conn, *revs):
    for r in revs:
        _run(conn, _load(r).upgrade)


def _cols(conn, table):
    return {c["name"] for c in sa.inspect(conn).get_columns(table)}


@pytest.fixture()
def conn():
    engine = sa.create_engine("sqlite://")
    with engine.begin() as c:
        yield c


def _add_user(conn, email="sam@example.com"):
    conn.execute(sa.text(
        "INSERT INTO users (email, role, is_active, created_at) VALUES (:e, 'staff', 1, '2026-01-01')"
    ), {"e": email})
    return conn.execute(sa.text("SELECT id FROM users WHERE email=:e"), {"e": email}).scalar()


def test_the_revision_chain_is_one_straight_line():
    mods = [_load(r) for r in CHAIN]
    assert [m.revision for m in mods] == CHAIN
    assert [m.down_revision for m in mods] == [None] + CHAIN[:-1]


def test_new_migration_adds_purpose_and_existing_rows_become_kyc(conn):
    _upgrade(conn, *CHAIN[:3])
    uid = _add_user(conn)
    conn.execute(sa.text(
        "INSERT INTO identity_verifications (public_id, user_id, provider, environment, status, created_at, updated_at) "
        "VALUES ('p1', :u, 'didit', 'sandbox', 'verified', '2026-01-01', '2026-01-01')"), {"u": uid})
    assert "purpose" not in _cols(conn, "identity_verifications")

    _upgrade(conn, CHAIN[3])
    assert "purpose" in _cols(conn, "identity_verifications")
    assert conn.execute(sa.text("SELECT purpose FROM identity_verifications WHERE public_id='p1'")).scalar() == "kyc"


def test_new_migration_drops_only_the_rekognition_columns_and_keeps_staff_rows(conn):
    _upgrade(conn, *CHAIN[:3])
    uid = _add_user(conn)
    conn.execute(sa.text(
        "INSERT INTO staff_credentials (user_id, staff_id_hash, face_id, face_enrolled_at, "
        "enroll_token_hash, failed_attempts, created_at) "
        "VALUES (:u, 'hash', 'rek-face-123', '2026-01-02', 'tok-hash', 2, '2026-01-01')"), {"u": uid})
    assert FACE_COLUMNS <= _cols(conn, "staff_credentials")

    _upgrade(conn, CHAIN[3])
    cols = _cols(conn, "staff_credentials")
    assert not (FACE_COLUMNS & cols)
    row = conn.execute(sa.text(
        "SELECT staff_id_hash, enroll_token_hash, failed_attempts FROM staff_credentials")).one()
    assert tuple(row) == ("hash", "tok-hash", 2)                       # Staff IDs/lockout state intact
    uniques = {tuple(u["column_names"]) for u in sa.inspect(conn).get_unique_constraints("staff_credentials")}
    assert ("enroll_token_hash",) in uniques and ("user_id",) in uniques


def test_downgrade_restores_the_shape_and_keeps_every_other_row(conn):
    _upgrade(conn, *CHAIN)
    uid = _add_user(conn)
    conn.execute(sa.text(
        "INSERT INTO staff_credentials (user_id, staff_id_hash, failed_attempts, created_at) "
        "VALUES (:u, 'hash', 0, '2026-01-01')"), {"u": uid})
    conn.execute(sa.text(
        "INSERT INTO identity_verifications (public_id, user_id, provider, environment, status, purpose, created_at, updated_at) "
        "VALUES ('p1', :u, 'didit', 'sandbox', 'verified', 'kyc', '2026-01-01', '2026-01-01')"), {"u": uid})

    _run(conn, _load(CHAIN[3]).downgrade)
    assert FACE_COLUMNS <= _cols(conn, "staff_credentials")             # shape is back (data is not)
    assert "purpose" not in _cols(conn, "identity_verifications")
    assert conn.execute(sa.text("SELECT staff_id_hash FROM staff_credentials")).scalar() == "hash"
    assert conn.execute(sa.text("SELECT COUNT(*) FROM identity_verifications")).scalar() == 1


def test_upgrade_downgrade_upgrade_is_repeatable(conn):
    _upgrade(conn, *CHAIN)
    for _ in range(2):
        _run(conn, _load(CHAIN[3]).downgrade)
        _upgrade(conn, CHAIN[3])
    assert "purpose" in _cols(conn, "identity_verifications")


def test_the_full_chain_matches_the_models(conn):
    """Guards the hand-written migrations against drifting from the SQLAlchemy models."""
    pytest.importorskip("flask_sqlalchemy")
    from app.extensions import db
    import app.models  # noqa: F401  (registers every table on db.metadata)

    _upgrade(conn, *CHAIN, *LATER_REVISIONS_ON_COMPARED_TABLES)
    insp = sa.inspect(conn)
    for name in ["users", "auth_events", "staff_credentials", *IDENTITY_TABLES]:
        model_cols = {c.name: c for c in db.metadata.tables[name].columns}
        db_cols = {c["name"]: c for c in insp.get_columns(name)}
        assert set(model_cols) == set(db_cols), f"{name}: columns differ"
        for col, mc in model_cols.items():
            assert mc.nullable == db_cols[col]["nullable"], f"{name}.{col}: nullability differs"

def _revision_graph():
    """{revision: down_revision} read from the real migration files."""
    import re
    graph = {}
    for path in VERSIONS.glob("*.py"):
        text = path.read_text(encoding="utf-8")
        rev = re.search(r"^revision\s*=\s*['\"](\w+)['\"]", text, re.M).group(1)
        down = re.search(r"^down_revision\s*=\s*(?:None|['\"](\w+)['\"])", text, re.M).group(1)
        graph[rev] = (down, path)
    return graph


def test_the_revision_graph_is_one_straight_line_with_a_single_head():
    graph = _revision_graph()
    heads = [r for r in graph if not any(d == r for d, _ in graph.values())]
    roots = [r for r, (d, _) in graph.items() if d is None]
    assert len(heads) == 1 and len(roots) == 1
    assert len({d for d, _ in graph.values() if d}) == len(graph) - 1          # no revision has two children
    seen, cur = [], heads[0]
    while cur:
        seen.append(cur)
        cur = graph[cur][0]
    assert set(seen) == set(graph)                                              # every revision reachable
    assert seen[::-1][: len(CHAIN)] == CHAIN                                    # identity chain is the real start


def test_skipped_revisions_do_not_touch_the_compared_tables():
    import re
    graph = _revision_graph()
    for rev in LATER_REVISIONS_ON_COMPARED_TABLES:
        cur = rev
        while cur and cur != CHAIN[-1]:
            cur = graph[cur][0]
        assert cur == CHAIN[-1], f"{rev} must descend from {CHAIN[-1]}"
    skipped = set(graph) - set(CHAIN) - set(LATER_REVISIONS_ON_COMPARED_TABLES)
    touching = re.compile(
        r"(alter_table|add_column|drop_column|alter_column|create_index|drop_index)\(\s*['\"]"
        r"(users|auth_events|staff_credentials|identity_verifications|identity_verification_events)['\"]")
    for rev in skipped:
        source = graph[rev][1].read_text(encoding="utf-8")
        assert not touching.search(source), f"{rev} changes a compared table; add it to LATER_REVISIONS_ON_COMPARED_TABLES"

