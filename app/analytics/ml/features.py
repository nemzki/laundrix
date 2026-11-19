"""Features for the disposal-risk model.

Only four plain numbers are used. Customer names, phone numbers and IDs are never features;
the customer's name is used only to count how many earlier orders that customer had.
"""

FEATURES = ("order_total", "is_paid", "previous_orders", "ready_on_weekend")

FEATURE_LABELS = {
    "order_total": "Order total",
    "is_paid": "Paid before pickup",
    "previous_orders": "Customer's earlier orders",
    "ready_on_weekend": "Ready on a weekend",
}


def normalize_name(name):
    """Lower-case and collapse spaces so 'Lester ' and 'lester' count as one customer."""
    return " ".join((name or "").lower().split())


def feature_vector(order_total, is_paid, previous_orders, ready_date):
    """Return the feature values in the same order as FEATURES."""
    return [
        float(order_total or 0),
        1.0 if is_paid else 0.0,
        float(previous_orders or 0),
        1.0 if ready_date.weekday() >= 5 else 0.0,
    ]


def previous_order_counts(rows):
    """How many earlier orders each customer had at the time of each order.

    rows: iterable of (key, customer_name, transaction_date, transaction_no).
    Returns {key: count}. Rows without a name always get 0.
    """
    counts = {}
    seen = {}
    for key, name, day, number in sorted(rows, key=lambda r: (r[2], r[3], str(r[0]))):
        who = normalize_name(name)
        if not who:
            counts[key] = 0
            continue
        counts[key] = seen.get(who, 0)
        seen[who] = counts[key] + 1
    return counts
