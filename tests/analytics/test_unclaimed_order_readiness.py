from datetime import datetime, timedelta

from app.analytics.ml.unclaimed_orders import summarize_unclaimed_history
from app.models import OrderStatus


def event(order_id, event_id, status, when):
    return (order_id, event_id, status, when)


def test_excludes_orders_without_full_30_day_observation_window():
    now = datetime(2026, 11, 15)
    rows = [event(1, 1, OrderStatus.READY, now - timedelta(days=29))]

    result = summarize_unclaimed_history(rows, as_of=now)

    assert result['eligible_samples'] == 0
    assert result['excluded_recent_orders'] == 1
    assert result['status'] == 'insufficient_data'


def test_pickup_exactly_30_days_after_latest_ready_is_within_window():
    now = datetime(2026, 11, 15)
    ready = now - timedelta(days=40)
    rows = [
        event(1, 1, OrderStatus.READY, ready),
        event(1, 2, OrderStatus.RELEASED, ready + timedelta(days=30)),
    ]

    result = summarize_unclaimed_history(rows, as_of=now)

    assert result['picked_up_within_30_days'] == 1
    assert result['not_picked_up_within_30_days'] == 0


def test_later_pickup_is_labeled_not_picked_up_within_30_days():
    now = datetime(2026, 11, 15)
    ready = now - timedelta(days=60)
    rows = [
        event(1, 1, OrderStatus.READY, ready),
        event(1, 2, OrderStatus.RELEASED, ready + timedelta(days=45)),
    ]

    result = summarize_unclaimed_history(rows, as_of=now)

    assert result['picked_up_within_30_days'] == 0
    assert result['not_picked_up_within_30_days'] == 1


def test_latest_ready_event_starts_a_new_observation_window():
    now = datetime(2026, 11, 15)
    first_ready = now - timedelta(days=100)
    latest_ready = now - timedelta(days=40)
    rows = [
        event(1, 1, OrderStatus.READY, first_ready),
        event(1, 2, OrderStatus.RELEASED, first_ready + timedelta(days=10)),
        event(1, 3, OrderStatus.READY, latest_ready),
    ]

    result = summarize_unclaimed_history(rows, as_of=now)

    assert result['picked_up_within_30_days'] == 0
    assert result['not_picked_up_within_30_days'] == 1


def test_completed_is_not_treated_as_customer_pickup():
    now = datetime(2026, 11, 15)
    ready = now - timedelta(days=40)
    rows = [
        event(1, 1, OrderStatus.READY, ready),
        event(1, 2, OrderStatus.COMPLETED, ready + timedelta(days=5)),
    ]

    result = summarize_unclaimed_history(rows, as_of=now)

    assert result['picked_up_within_30_days'] == 0
    assert result['not_picked_up_within_30_days'] == 1
