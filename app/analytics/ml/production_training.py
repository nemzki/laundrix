"""Training and serving helpers for models trained on genuine Laundrix history."""
from datetime import datetime, timezone
import json
from pathlib import Path

import joblib
import numpy as np
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, f1_score, precision_score, recall_score, roc_auc_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from app.analytics.ml.demo_training import FEATURES
from app.analytics.ml.unclaimed_orders import (
    MINIMUM_ELIGIBLE_SAMPLES,
    MINIMUM_PER_CLASS,
    get_unclaimed_training_rows,
)
from app.extensions import db
from app.models import Order, OrderItem, OrderStatus, OrderStatusHistory


def _classification_metrics(model, features, labels):
    predicted = model.predict(features)
    probabilities = model.predict_proba(features)[:, 1]
    return {
        "accuracy": round(float(accuracy_score(labels, predicted)), 4),
        "precision": round(float(precision_score(labels, predicted, zero_division=0)), 4),
        "recall": round(float(recall_score(labels, predicted, zero_division=0)), 4),
        "f1": round(float(f1_score(labels, predicted, zero_division=0)), 4),
        "roc_auc": round(float(roc_auc_score(labels, probabilities)), 4),
    }


def train_production_model(instance_path, as_of=None):
    """Train and evaluate only from eligible real database history.

    Chronological 70/15/15 train/validation/test split. The final test segment
    is never used to choose the model. If any segment lacks both classes, the
    operation stops instead of reporting misleading metrics.
    """
    examples = get_unclaimed_training_rows(as_of=as_of)
    labels = np.asarray([row["label"] for row in examples], dtype=int)
    eligible = len(examples)
    class_counts = {"picked_up_within_30_days": int((labels == 0).sum()),
                    "not_picked_up_within_30_days": int((labels == 1).sum())}
    if eligible < MINIMUM_ELIGIBLE_SAMPLES:
        raise ValueError(
            f"Only {eligible} eligible historical orders; {MINIMUM_ELIGIBLE_SAMPLES} are required."
        )
    if min(class_counts.values()) < MINIMUM_PER_CLASS:
        raise ValueError(
            f"Outcome classes are imbalanced for training: {class_counts}. "
            f"At least {MINIMUM_PER_CLASS} examples in each outcome are required."
        )

    x = np.asarray([[row["features"][name] for name in FEATURES] for row in examples], dtype=float)
    n = len(examples)
    train_end = int(n * 0.70)
    validation_end = int(n * 0.85)
    y_train, y_validation, y_test = labels[:train_end], labels[train_end:validation_end], labels[validation_end:]
    x_train, x_validation, x_test = x[:train_end], x[train_end:validation_end], x[validation_end:]

    for split_name, split_labels in (("training", y_train), ("validation", y_validation), ("test", y_test)):
        if len(np.unique(split_labels)) < 2:
            raise ValueError(
                f"Chronological {split_name} segment contains only one outcome class. "
                "Collect more genuine historical orders before training."
            )

    candidates = {
        "logistic_regression": Pipeline([
            ("scale", StandardScaler()),
            ("model", LogisticRegression(max_iter=1500, class_weight="balanced")),
        ]),
        "random_forest": RandomForestClassifier(
            n_estimators=300, min_samples_leaf=3, class_weight="balanced",
            random_state=42, n_jobs=-1,
        ),
    }
    validation_metrics = {}
    fitted = {}
    for name, model in candidates.items():
        model.fit(x_train, y_train)
        validation_metrics[name] = _classification_metrics(model, x_validation, y_validation)
        fitted[name] = model

    selected = max(validation_metrics, key=lambda name: validation_metrics[name]["f1"])
    selected_model = fitted[selected]
    test_metrics = _classification_metrics(selected_model, x_test, y_test)
    output_dir = Path(instance_path) / "ml-production"
    output_dir.mkdir(parents=True, exist_ok=True)
    metadata = {
        "model_type": "production_historical_model",
        "training_data": "genuine_laundrix_database_history",
        "is_production_model": True,
        "trained_at": datetime.now(timezone.utc).isoformat(),
        "eligible_samples": eligible,
        "class_counts": class_counts,
        "training_samples": int(len(y_train)),
        "validation_samples": int(len(y_validation)),
        "testing_samples": int(len(y_test)),
        "selected_model": selected,
        "validation_metrics": validation_metrics,
        "held_out_test_metrics": test_metrics,
        "first_ready_at": examples[0]["ready_at"].isoformat(),
        "last_ready_at": examples[-1]["ready_at"].isoformat(),
        "features": FEATURES,
        "warning": "Model evaluation is historical and does not guarantee future performance.",
    }
    joblib.dump({"model": selected_model, "features": FEATURES, "metadata": metadata},
                output_dir / "unclaimed_order_model.joblib")
    (output_dir / "unclaimed_order_model_metrics.json").write_text(
        json.dumps(metadata, indent=2), encoding="utf-8"
    )
    return metadata


def load_production_model_summary(instance_path):
    directory = Path(instance_path) / "ml-production"
    path = directory / "unclaimed_order_model_metrics.json"
    if not path.is_file() or not (directory / "unclaimed_order_model.joblib").is_file():
        return None
    try:
        metadata = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if metadata.get("model_type") != "production_historical_model" or metadata.get("is_production_model") is not True:
        return None
    return metadata


def get_current_ready_order_predictions(instance_path, limit=10):
    """Predict risk only for currently-ready orders using an approved real-data model."""
    artifact = Path(instance_path) / "ml-production" / "unclaimed_order_model.joblib"
    if not artifact.is_file():
        return []
    try:
        bundle = joblib.load(artifact)
        metadata = bundle.get("metadata", {})
        model = bundle.get("model")
        if (metadata.get("is_production_model") is not True or model is None
                or bundle.get("features") != FEATURES):
            return []
    except Exception:  # a missing/corrupt artifact must not break analytics
        return []

    ready_orders = db.session.execute(
        db.select(Order.id, Order.reference, Order.total, Order.created_at)
        .where(Order.status == OrderStatus.READY)
        .order_by(Order.created_at.desc())
        .limit(limit)
    ).all()
    if not ready_orders:
        return []
    order_ids = [row.id for row in ready_orders]
    item_rows = db.session.execute(
        db.select(OrderItem.order_id, OrderItem.item_type, OrderItem.quantity)
        .where(OrderItem.order_id.in_(order_ids))
    ).all()
    items_by_order = {}
    for order_id, item_type, quantity in item_rows:
        bucket = items_by_order.setdefault(order_id, [])
        bucket.append((item_type, float(quantity or 0)))
    history_rows = db.session.execute(
        db.select(OrderStatusHistory.order_id, OrderStatusHistory.created_at)
        .where(OrderStatusHistory.order_id.in_(order_ids),
               OrderStatusHistory.to_status == OrderStatus.READY)
        .order_by(OrderStatusHistory.created_at.desc(), OrderStatusHistory.id.desc())
    ).all()
    ready_dates = {}
    for order_id, created_at in history_rows:
        ready_dates.setdefault(order_id, created_at)

    predictions = []
    for order in ready_orders:
        ready_at = ready_dates.get(order.id)
        if ready_at is None:
            continue
        items = items_by_order.get(order.id, [])
        features = [
            float(order.total or 0), len(items), sum(qty for _, qty in items),
            sum(1 for item_type, _ in items if item_type == "service"),
            max(0, (ready_at - order.created_at).days), ready_at.weekday(), ready_at.month,
        ]
        probability = float(model.predict_proba(np.asarray([features], dtype=float))[0, 1])
        predictions.append({
            "reference": order.reference,
            "score_percent": round(probability * 100, 1),
            "score_band": "High" if probability >= 0.7 else "Moderate" if probability >= 0.4 else "Low",
        })
    return predictions
