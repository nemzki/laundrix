"""Synthetic-only model training used to demonstrate the ML workflow.

No synthetic rows are inserted into MySQL. Artifacts are written under the
Flask instance directory and are explicitly marked as development-only.
"""
from datetime import datetime, timezone
import json
from pathlib import Path

import joblib
import numpy as np
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, f1_score, precision_score, recall_score, roc_auc_score
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

FEATURES = [
    "order_total", "item_count", "total_quantity", "service_count",
    "days_to_ready", "ready_weekday", "ready_month",
]


def make_demo_dataset(samples=800, random_state=42):
    """Generate reproducible synthetic examples; this is not real shop history."""
    rng = np.random.default_rng(random_state)
    order_total = np.clip(rng.lognormal(mean=5.8, sigma=0.65, size=samples), 100, 5000)
    item_count = rng.integers(1, 8, size=samples)
    total_quantity = np.maximum(item_count, rng.integers(1, 18, size=samples))
    service_count = np.minimum(rng.integers(1, 5, size=samples), item_count)
    days_to_ready = rng.integers(0, 8, size=samples)
    ready_weekday = rng.integers(0, 7, size=samples)
    ready_month = rng.integers(1, 13, size=samples)

    # Deliberately synthetic relationship, used only to test training mechanics.
    logit = (
        0.0 + (order_total / 1800.0) + (days_to_ready * 0.13)
        - (item_count * 0.10) - (total_quantity * 0.035)
        - (service_count * 0.12) + np.where(ready_weekday >= 5, 0.18, 0.0)
    )
    probability = 1.0 / (1.0 + np.exp(-logit))
    labels = (rng.random(samples) < probability).astype(int)
    # Ensure the demo can always demonstrate both classes without pretending
    # that this forced balancing reflects real Laundrix outcomes.
    if labels.sum() < 2:
        labels[:2] = 1
    if labels.sum() > samples - 2:
        labels[:2] = 0

    features = np.column_stack([
        order_total, item_count, total_quantity, service_count,
        days_to_ready, ready_weekday, ready_month,
    ])
    return features, labels


def _metrics(model, x_test, y_test):
    predicted = model.predict(x_test)
    probability = model.predict_proba(x_test)[:, 1]
    return {
        "accuracy": round(float(accuracy_score(y_test, predicted)), 4),
        "precision": round(float(precision_score(y_test, predicted, zero_division=0)), 4),
        "recall": round(float(recall_score(y_test, predicted, zero_division=0)), 4),
        "f1": round(float(f1_score(y_test, predicted, zero_division=0)), 4),
        "roc_auc": round(float(roc_auc_score(y_test, probability)), 4),
    }


def train_demo_models(instance_path, samples=800, random_state=42):
    """Train two classifiers on synthetic data and save a dev-only artifact."""
    if samples < 200:
        raise ValueError("Use at least 200 synthetic samples for the demo training run.")

    x, y = make_demo_dataset(samples=samples, random_state=random_state)
    x_train, x_test, y_train, y_test = train_test_split(
        x, y, test_size=0.2, random_state=random_state, stratify=y,
    )

    candidates = {
        "logistic_regression": Pipeline([
            ("scale", StandardScaler()),
            ("model", LogisticRegression(max_iter=1000, class_weight="balanced")),
        ]),
        "random_forest": RandomForestClassifier(
            n_estimators=250, min_samples_leaf=3, class_weight="balanced",
            random_state=random_state, n_jobs=-1,
        ),
    }
    results = {}
    fitted = {}
    for name, model in candidates.items():
        model.fit(x_train, y_train)
        results[name] = _metrics(model, x_test, y_test)
        fitted[name] = model

    selected = max(results, key=lambda name: results[name]["f1"])
    selected_model = fitted[selected]
    # These are intentionally synthetic example inputs, never live orders.
    preview_inputs = np.asarray([
        [450, 2, 4, 2, 2, 1, 6],
        [1800, 6, 12, 3, 6, 5, 11],
        [900, 3, 7, 2, 1, 2, 3],
    ], dtype=float)
    preview = [
        round(float(value) * 100, 1)
        for value in selected_model.predict_proba(preview_inputs)[:, 1]
    ]

    output_dir = Path(instance_path) / "ml-development"
    output_dir.mkdir(parents=True, exist_ok=True)
    artifact_path = output_dir / "unclaimed_order_demo.joblib"
    metadata_path = output_dir / "unclaimed_order_demo_metrics.json"
    metadata = {
        "model_type": "development_demo_only",
        "training_data": "synthetic_generated_in_memory",
        "is_production_model": False,
        "trained_at": datetime.now(timezone.utc).isoformat(),
        "samples": int(samples),
        "training_samples": int(len(y_train)),
        "testing_samples": int(len(y_test)),
        "class_counts": {"picked_up_within_30_days": int((y == 0).sum()),
                          "not_picked_up_within_30_days": int((y == 1).sum())},
        "selected_model": selected,
        "metrics": results,
        "demo_prediction_percentages": preview,
        "features": FEATURES,
        "warning": "Trained only on synthetic data. Do not use for real customer/order decisions.",
    }
    joblib.dump({"model": selected_model, "features": FEATURES, "metadata": metadata}, artifact_path)
    metadata_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    return metadata


def load_demo_training_summary(instance_path):
    """Load demo metadata for display; never loads the estimator into production serving."""
    directory = Path(instance_path) / "ml-development"
    path = directory / "unclaimed_order_demo_metrics.json"
    if not path.is_file() or not (directory / "unclaimed_order_demo.joblib").is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if data.get("model_type") != "development_demo_only" or data.get("is_production_model") is not False:
        return None
    return data
