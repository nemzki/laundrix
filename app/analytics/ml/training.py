"""Train the unclaimed-order model from Laundrix's own confirmed orders, only when it is safe."""
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError

from app.analytics.ml import model as ml
from app.analytics.ml.features import FEATURES
from app.analytics.ml.policy import (
    DISPOSAL_DAYS,
    MIN_PER_OUTCOME,
    MIN_ROC_AUC,
    MIN_TRAINING_ORDERS,
    RETRAIN_AFTER_NEW,
    TEST_FRACTION,
)
from app.analytics.ml.system_data import DISPOSED, load_records, summarize, training_rows
from app.extensions import db
from app.models import UnclaimedModelRun

SYSTEM = "system"


class NotReady(ValueError):
    """Not enough confirmed orders yet (a normal state, not an error)."""


class NotReliable(ValueError):
    """Trained, but the model does not beat chance on held-out orders, so it is not used."""


def get_active_run():
    return db.session.execute(
        db.select(UnclaimedModelRun)
        .where(UnclaimedModelRun.data_source == SYSTEM, UnclaimedModelRun.is_active.is_(True))
        .order_by(UnclaimedModelRun.version.desc()).limit(1)
    ).scalar_one_or_none()


def train_model(records=None, today=None):
    """Train on confirmed orders and save a new active version. Raises NotReady / NotReliable."""
    if records is None:
        records, today = load_records(today)
    info = summarize(records, today)
    if not info["enough"]:
        raise NotReady(
            "Machine learning is not ready. More order records are needed for reliable training "
            f"({'; '.join(info['missing'])})."
        )

    rows = training_rows(records)
    x = [r["features"] for r in rows]
    y = [1 if r["outcome"] == DISPOSED else 0 for r in rows]
    split = int(len(rows) * (1 - TEST_FRACTION))
    for name, part in (("training", y[:split]), ("test", y[split:])):
        if len(set(part)) < 2:
            raise NotReady(
                f"Machine learning is not ready. The {name} part of the data has only one outcome; "
                "more orders with both outcomes are needed."
            )

    # 1) fit on the older orders, measure on the newest ones (an honest, time-based test)
    metrics = ml.evaluate(ml.fit(x[:split], y[:split]), x[split:], y[split:])
    if metrics["roc_auc"] < MIN_ROC_AUC:
        raise NotReliable(
            f"The model is not reliable yet (ROC-AUC {metrics['roc_auc']:.2f}, "
            f"needs at least {MIN_ROC_AUC:.2f}). Predictions are hidden until more data is available."
        )
    # 2) the saved model is refit on every confirmed order
    params = ml.fit(x, y)

    last = db.session.scalar(db.select(func.max(UnclaimedModelRun.version))) or 0
    try:
        db.session.execute(
            db.update(UnclaimedModelRun)
            .where(UnclaimedModelRun.data_source == SYSTEM).values(is_active=False)
        )
        run = UnclaimedModelRun(
            version=last + 1, is_active=True, algorithm=ml.ALGORITHM, features=list(FEATURES),
            params=params, metrics=metrics, n_orders=len(rows), n_disposed=sum(y),
            data_start=rows[0]["ready_date"], data_end=rows[-1]["ready_date"],
            disposal_days=DISPOSAL_DAYS, labels_simulated=False, data_source=SYSTEM,
        )
        db.session.add(run)
        db.session.commit()
    except IntegrityError:           # two requests trained at the same moment; the other one won
        db.session.rollback()
        run = get_active_run()
    except Exception:
        db.session.rollback()
        raise
    return run


NOT_READY_MESSAGE = "Machine learning is not ready. More order records are needed for reliable training."


def ensure_model(records, today):
    """Called when an admin opens Analytics: train or retrain automatically when appropriate.

    Returns (active_run_or_None, status, message, summary_dict) where status is one of
    "trained", "not_ready", "not_reliable" or "error". Never raises for a normal
    'not enough data' situation, and a failed retraining never removes a working model.
    """
    info = summarize(records, today)
    run = get_active_run()
    status, message = None, None
    due = info["enough"] and (run is None or info["labelled"] >= run.n_orders + RETRAIN_AFTER_NEW)
    if due:
        try:
            run = train_model(records, today) or run
        except NotReady as exc:
            status, message = "not_ready", str(exc)
        except NotReliable as exc:
            status, message = "not_reliable", str(exc)
        except Exception:  # never break the page because training failed
            db.session.rollback()
            status, message = "error", "Training could not be completed right now. Please try again later."
    if run is not None:
        return run, "trained", message, info
    if status is None:
        status = "not_ready"
    return None, status, message or NOT_READY_MESSAGE, info
