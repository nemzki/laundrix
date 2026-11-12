"""Data-quality checks (pure: no database, no Flask).

Findings are returned as ``Issue`` objects with counts only.  Nothing here ever sees, stores or
returns customer names, contact details or any other personal data.
"""
from __future__ import annotations

from datetime import date, timedelta

from app.analytics.ml.policy import Policy
from app.analytics.ml.schemas import Issue, Severity


def zero_runs(values, min_len: int) -> list[tuple[int, int]]:
    """(start_index, length) of every run of consecutive zeros that is at least ``min_len`` long."""
    runs, i, n = [], 0, len(values)
    while i < n:
        if values[i] == 0:
            j = i
            while j < n and values[j] == 0:
                j += 1
            if j - i >= min_len:
                runs.append((i, j - i))
            i = j
        else:
            i += 1
    return runs


def active_window_start(values, min_gap: int) -> int:
    """Index where the usable history begins: just after the LAST run of ``min_gap``+ zeros.

    0 means no gap (use everything).  ``len(values)`` means the history ends inside a gap, so
    there is no recent activity to learn from.
    """
    runs = zero_runs(values, min_gap)
    if not runs:
        return 0
    start, length = runs[-1]
    return start + length


def longest_zero_run(values) -> int:
    best = cur = 0
    for v in values:
        cur = cur + 1 if v == 0 else 0
        best = max(best, cur)
    return best


def zero_ratio(values) -> float:
    return 0.0 if not len(values) else sum(1 for v in values if v == 0) / len(values)


def closed_weekdays(values, start: date, min_occurrences: int = 4) -> list[int]:
    """Weekdays (Monday=0) with zero activity on EVERY occurrence, seen at least ``min_occurrences``
    times.  Likely a regular closing day; the weekday feature models it, so this is informational."""
    seen = {i: 0 for i in range(7)}
    nonzero = {i: 0 for i in range(7)}
    for i, v in enumerate(values):
        wd = (start + timedelta(days=i)).weekday()
        seen[wd] += 1
        if v != 0:
            nonzero[wd] += 1
    return [wd for wd in range(7) if seen[wd] >= min_occurrences and nonzero[wd] == 0]


_WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")


def series_issues(values, start: date, policy: Policy, excluded_before_gap: int = 0) -> list[Issue]:
    """Observations about a daily series (call with the usable window)."""
    out: list[Issue] = []
    if excluded_before_gap:
        out.append(Issue(
            "history_before_gap", Severity.WARNING,
            f"{excluded_before_gap} day(s) of earlier history were not used because activity stopped for "
            f"{policy.max_inactive_gap_days}+ consecutive days afterwards (treated as a data gap).",
            excluded_before_gap))
    if len(values) and zero_ratio(values) >= policy.zero_day_ratio_warning:
        zeros = sum(1 for v in values if v == 0)
        out.append(Issue(
            "many_zero_days", Severity.INFO,
            f"{zeros} of {len(values)} days had no activity; forecasts for such sparse data are inherently noisy.",
            zeros))
    for wd in closed_weekdays(values, start):
        out.append(Issue("closed_weekday", Severity.INFO,
                         f"No activity on any {_WEEKDAYS[wd]} in this window (treated as a regular closing day).", 1))
    return out


def quality_issues(counts: dict) -> list[Issue]:
    """Turn the database's record counts into issues.  ``counts`` holds numbers only."""
    out: list[Issue] = []
    n = counts.get("awaiting_receipt", 0)
    if n:
        out.append(Issue("awaiting_receipt", Severity.INFO,
                         f"{n} order(s) are not yet confirmed as received and are excluded from demand history.", n))
    n = counts.get("invalid_received_before_created", 0)
    if n:
        out.append(Issue("received_before_created", Severity.WARNING,
                         f"{n} order(s) have a received time earlier than their creation time and are excluded.", n))
    n = counts.get("invalid_received_future", 0)
    if n:
        out.append(Issue("received_in_future", Severity.WARNING,
                         f"{n} order(s) have a received time in the future and are excluded.", n))
    n = counts.get("eligible_without_items", 0)
    if n:
        out.append(Issue("orders_without_items", Severity.INFO,
                         f"{n} eligible order(s) have no items; they count as orders but not toward service demand.", n))
    n = counts.get("possible_duplicate_groups", 0)
    if n:
        out.append(Issue("possible_duplicates", Severity.WARNING,
                         f"{n} group(s) of orders share the same customer, total and day. Review for accidental "
                         "duplicates (they are NOT removed automatically).", n))
    return out
