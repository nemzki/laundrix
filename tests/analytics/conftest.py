"""Analytics test setup: reuse the existing app/user fixtures from tests/laundry."""
import pytest

from tests.laundry.conftest import (  # noqa: F401  (fixtures re-exported for this package)
    admin, admin_client, anon_client, app, staff, staff_client,
)
from tests.analytics import factories as f
from app.extensions import db
from app.payments.seed import seed_payments


@pytest.fixture()
def payment_methods(app):
    seed_payments()


@pytest.fixture()
def dataset(app, payment_methods):
    """A small ledger whose every aggregate is verified by hand in test_queries.py.

    Dates are Philippine local times.  Range under test P = Nov 1-7 2026;
    its comparison period is Oct 25-31 2026.

      order  customer  local created     total  status      paid / notes
      O1     Ana       Oct 28 10:00       200   completed   cash 200 (Oct 28)            -> fully paid
      O6     Ana       Oct 31 23:59:59     40   received     nothing                     -> unpaid, last second of prior period
      O2     Ana       Nov 2 09:00        300   processing   cash 100 (Nov 2), gcash 50 (Nov 3)  -> partial, balance 150
      O3     Ben       Nov 2 23:30        100   ready        cash 100 (Nov 2), REVERSED Nov 8   -> net 0, unpaid
      O4     Cara      Nov 3 00:00:00      80   received     nothing, receipt not confirmed     -> unpaid, first second of Nov 3
      O5     Dan       Nov 4 12:00        500   completed   legacy: payment not tracked
      O7     Ben       Nov 8 00:00:00      60   received     nothing                     -> first instant AFTER P (excluded)
    """
    ana = f.make_customer("Ana Cruz", f.local(2026, 10, 20, 10))
    ben = f.make_customer("Ben Reyes", f.local(2026, 11, 2, 9))
    cara = f.make_customer("Cara Lim", f.local(2026, 11, 3, 0))
    dan = f.make_customer("Dan Uy", f.local(2026, 11, 4, 12))

    o1 = f.make_order(ana, 200, f.local(2026, 10, 28, 10), "completed")
    f.add_payment(o1, 200, f.local(2026, 10, 28, 10, 5), "cash")
    o6 = f.make_order(ana, 40, f.local(2026, 10, 31, 23, 59, 59), "order_received")
    o2 = f.make_order(ana, 300, f.local(2026, 11, 2, 9), "processing", items=[
        ("service", "Wash", 2, "load", 160), ("package", "Wash, Dry & Fold", 1, "package", 100),
        ("addon", "Fabcon", 2, "pc", 40)])
    f.add_payment(o2, 100, f.local(2026, 11, 2, 9, 5), "cash")
    f.add_payment(o2, 50, f.local(2026, 11, 3, 10), "gcash")
    o3 = f.make_order(ben, 100, f.local(2026, 11, 2, 23, 30), "ready_for_pickup", items=[
        ("service", "Wash", 1, "load", 80), ("addon", "Fabcon", 1, "pc", 20)])
    p3 = f.add_payment(o3, 100, f.local(2026, 11, 2, 23, 35), "cash")
    f.add_reversal(p3, f.local(2026, 11, 8, 9))
    o4 = f.make_order(cara, 80, f.local(2026, 11, 3, 0), "order_received", received=False, items=[
        ("service", "Wash", 1, "load", 80)])
    o5 = f.make_order(dan, 500, f.local(2026, 11, 4, 12), "completed", tracked=False, items=[
        ("package", "Wash, Dry & Fold", 2, "package", 500)])
    o7 = f.make_order(ben, 60, f.local(2026, 11, 8, 0), "order_received")
    db.session.commit()
    return {"ana": ana, "ben": ben, "cara": cara, "dan": dan,
            "o1": o1, "o2": o2, "o3": o3, "o4": o4, "o5": o5, "o6": o6, "o7": o7}
