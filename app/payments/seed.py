"""Idempotent defaults. Never overwrites rows an Admin has edited, and never invents account details."""
from app.extensions import db
from app.models import PaymentMethod, PaymentSettings

DEFAULT_METHODS = [  # code, label, requires_reference, sort_order
    ("cash", "Cash", False, 10),
    ("gcash", "GCash", False, 20),
]


def seed_payments():
    """Returns (methods_added, settings_added)."""
    methods = 0
    for code, label, requires_reference, order in DEFAULT_METHODS:
        if not db.session.execute(db.select(PaymentMethod).filter_by(code=code)).scalar_one_or_none():
            db.session.add(PaymentMethod(code=code, label=label, requires_reference=requires_reference,
                                         sort_order=order, is_active=True))
            methods += 1
    settings = 0
    if db.session.get(PaymentSettings, 1) is None:
        db.session.add(PaymentSettings(id=1))
        settings = 1
    db.session.commit()
    return methods, settings
