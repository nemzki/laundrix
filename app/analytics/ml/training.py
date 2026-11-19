"""Train the disposal-risk model from imported historical transactions and save it."""
from datetime import datetime, timedelta

from sqlalchemy import func

from app.analytics.ml import model as ml
from app.analytics.ml.features import FEATURES, feature_vector, previous_order_counts
from app.analytics.ml.policy import (
    DISPOSAL_DAYS,
    MIN_PER_OUTCOME,
    MIN_TRAINING_ORDERS,
    TEST_FRACTION,
)
from app.core.timeutil import SHOP_TZ
from app.extensions import db
from app.models import HistoricalTransaction, UnclaimedModelRun


def shop_today():
    return datetime.now(SHOP_TZ).date()


def load_training_rows(as_of=None):
    """Mature orders with a known outcome, oldest first, as (features, label, row).

    Mature = ready at least DISPOSAL_DAYS ago, so "claimed" and "disposed" are both final.
    Newer orders are left out; otherwise they could only ever look "claimed".
    """
    today = as_of or shop_today()
    cutoff = today - timedelta(days=DISPOSAL_DAYS)

    everyone = db.session.execute(
        db.select(
            HistoricalTransaction.id,
            HistoricalTransaction.customer_name,
            HistoricalTransaction.transaction_date,
            HistoricalTransaction.source_transaction_no,
        )
    ).all()
    previous = previous_order_counts((r.id, r.customer_name, r.transaction_date, r.source_transaction_no)
                                     for r in everyone)

    rows = db.session.execute(
        db.select(HistoricalTransaction)
        .where(
            HistoricalTransaction.outcome_status.in_(("claimed", "disposed")),
            HistoricalTransaction.ready_date.is_not(None),
            HistoricalTransaction.ready_date <= cutoff,
        )
        .order_by(HistoricalTransaction.ready_date, HistoricalTransaction.id)
    ).scalars().all()

    return [
        (
            feature_vector(
                row.total_amount,
                row.payment_status == "paid",
                previous.get(row.id, 0),
                row.ready_date,
            ),
            1 if row.outcome_status == "disposed" else 0,
            row,
        )
        for row in rows
    ]


def train_model(as_of=None):
    """Train, test on the newest part of the data, then save a new active model version."""
    rows = load_training_rows(as_of)
    labels = [label for _, label, _ in rows]
    disposed = sum(labels)
    claimed = len(labels) - disposed

    if len(rows) < MIN_TRAINING_ORDERS:
        raise ValueError(
            f"Only {len(rows)} mature orders with a known outcome; "
            f"at least {MIN_TRAINING_ORDERS} are needed."
        )
    if min(claimed, disposed) < MIN_PER_OUTCOME:
        raise ValueError(
            f"Not enough of each outcome (claimed: {claimed}, disposed: {disposed}); "
            f"at least {MIN_PER_OUTCOME} of each are needed."
        )

    x = [features for features, _, _ in rows]
    split = int(len(rows) * (1 - TEST_FRACTION))
    x_train, y_train, x_test, y_test = x[:split], labels[:split], x[split:], labels[split:]
    for name, part in (("training", y_train), ("test", y_test)):
        if len(set(part)) < 2:
            raise ValueError(
                f"The {name} part contains only one outcome. Add more history before training."
            )

    # 1) fit on the older part and measure on the newer part (honest test)
    metrics = ml.evaluate(ml.fit(x_train, y_train), x_test, y_test)
    # 2) the saved model is refit on everything so it learns from the newest orders too
    params = ml.fit(x, labels)

    sources = {row.status_source for _, _, row in rows}
    last_version = db.session.scalar(db.select(func.max(UnclaimedModelRun.version))) or 0
    try:
        db.session.execute(db.update(UnclaimedModelRun).values(is_active=False))
        run = UnclaimedModelRun(
            version=last_version + 1,
            is_active=True,
            algorithm=ml.ALGORITHM,
            features=list(FEATURES),
            params=params,
            metrics=metrics,
            n_orders=len(rows),
            n_disposed=disposed,
            data_start=rows[0][2].ready_date,
            data_end=rows[-1][2].ready_date,
            disposal_days=DISPOSAL_DAYS,
            labels_simulated=sources != {"recorded"},
        )
        db.session.add(run)
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise
    return run
