"""Reuse the standard Laundrix test app/users (in-memory SQLite) for the audit-log tests."""
from datetime import datetime, timedelta, timezone

import pytest

from app.extensions import db
from app.models import AuditLog
from app.payments.seed import seed_payments
from tests.laundry.conftest import (  # noqa: F401  (fixtures)
    admin, admin_client, anon_client, app, catalog, staff, staff_client,
)


@pytest.fixture()
def pay(catalog):
    seed_payments()


def add_row(minutes_ago=0, *, name="Sam Cruz", role="staff", action="update", module="orders",
            description="Updated something", success=True, when=None, **extra):
    """Insert an audit row directly with a chosen timestamp (naive UTC)."""
    row = AuditLog(
        actor_name=name, actor_role=role, action=action, module=module, description=description,
        success=success,
        created_at=when or (datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(minutes=minutes_ago)), **extra)
    db.session.add(row)
    db.session.commit()
    return row
