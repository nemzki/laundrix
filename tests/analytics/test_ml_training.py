from datetime import datetime

from app.analytics.ml.demo_training import (
    load_demo_training_summary,
    make_demo_dataset,
    train_demo_models,
)
from app.analytics.ml.unclaimed_orders import build_unclaimed_training_rows


def test_synthetic_demo_dataset_has_expected_features_and_both_classes():
    features, labels = make_demo_dataset(samples=500, random_state=7)
    assert features.shape == (500, 7)
    assert set(labels.tolist()) == {0, 1}


def test_demo_training_saves_only_development_artifacts(tmp_path):
    metadata = train_demo_models(tmp_path, samples=500, random_state=11)
    summary = load_demo_training_summary(tmp_path)

    assert metadata["is_production_model"] is False
    assert metadata["training_data"] == "synthetic_generated_in_memory"
    assert summary["model_type"] == "development_demo_only"
    assert (tmp_path / "ml-development" / "unclaimed_order_demo.joblib").is_file()
    assert (tmp_path / "ml-development" / "unclaimed_order_demo_metrics.json").is_file()
    assert not (tmp_path / "ml-production").exists()


def test_real_history_builder_labels_only_fully_observed_latest_ready_spell():
    as_of = datetime(2026, 11, 15)
    orders = [
        (1, 500, datetime(2026, 9, 20)),
        (2, 900, datetime(2026, 9, 20)),
        (3, 700, datetime(2026, 10, 25)),
    ]
    items = [
        (1, "service", 2), (1, "addon", 1),
        (2, "service", 4),
        (3, "service", 3),
    ]
    history = [
        (1, 1, "ready_for_pickup", datetime(2026, 10, 1)),
        (1, 2, "picked_up", datetime(2026, 10, 5)),
        (2, 3, "ready_for_pickup", datetime(2026, 10, 1)),
        (3, 4, "ready_for_pickup", datetime(2026, 11, 1)),
    ]

    rows = build_unclaimed_training_rows(orders, items, history, as_of=as_of)

    assert len(rows) == 2
    assert rows[0]["order_id"] == 1 and rows[0]["label"] == 0
    assert rows[1]["order_id"] == 2 and rows[1]["label"] == 1
    assert rows[0]["features"]["item_count"] == 2
    assert rows[0]["features"]["total_quantity"] == 3
    assert rows[0]["features"]["service_count"] == 1
