"""Data-quality checks."""
from datetime import date

from app.analytics.ml import data_validation as dv
from app.analytics.ml.policy import DEFAULT_POLICY


def test_zero_runs_threshold():
    assert dv.zero_runs([1] + [0] * 13 + [1], 14) == []                # 13 zeros: not a gap
    assert dv.zero_runs([1] + [0] * 14 + [1], 14) == [(1, 14)]         # 14 zeros: a gap
    assert dv.zero_runs([0, 0, 1, 0, 0, 0], 2) == [(0, 2), (3, 3)]
    assert dv.zero_runs([], 3) == []


def test_active_window_start():
    assert dv.active_window_start([1, 0, 0, 1, 1], 14) == 0           # no gap: use everything
    assert dv.active_window_start([1] + [0] * 5 + [1, 1], 5) == 6     # history restarts after the gap
    assert dv.active_window_start([1, 1] + [0] * 6, 5) == 8           # ends inside a gap -> len(values)
    runs_first_then_second = [1] + [0] * 5 + [1] + [0] * 6 + [1]
    assert dv.active_window_start(runs_first_then_second, 5) == 13    # the LAST gap decides


def test_longest_run_and_ratio():
    assert dv.longest_zero_run([0, 0, 1, 0, 0, 0, 1]) == 3
    assert dv.longest_zero_run([]) == 0
    assert dv.zero_ratio([0, 1, 0, 1]) == 0.5 and dv.zero_ratio([]) == 0.0


def test_closed_weekdays_need_enough_occurrences():
    start = date(2026, 1, 5)                                          # Monday
    # 5 full weeks, nothing ever on Sunday (index 6)
    values = [1, 2, 1, 3, 2, 4, 0] * 5
    assert dv.closed_weekdays(values, start) == [6]
    assert dv.closed_weekdays(values[:20], start) == []              # Sunday seen only 2 times: not enough evidence


def test_series_issues():
    start = date(2026, 1, 5)
    values = [0] * 7 + [1] * 3                                        # 70% zero days
    codes = {i.code for i in dv.series_issues(values, start, DEFAULT_POLICY)}
    assert "many_zero_days" in codes
    issues = dv.series_issues([1] * 10, start, DEFAULT_POLICY, excluded_before_gap=49)
    gap = [i for i in issues if i.code == "history_before_gap"][0]
    assert gap.count == 49 and "14" in gap.message and gap.severity == "warning"
    assert dv.series_issues([], start, DEFAULT_POLICY) == []


def test_quality_issues_only_report_what_exists():
    assert dv.quality_issues({}) == []
    assert dv.quality_issues({"awaiting_receipt": 0, "possible_duplicate_groups": 0}) == []
    got = {i.code: i for i in dv.quality_issues({
        "awaiting_receipt": 3, "invalid_received_before_created": 2, "invalid_received_future": 1,
        "eligible_without_items": 4, "possible_duplicate_groups": 5})}
    assert set(got) == {"awaiting_receipt", "received_before_created", "received_in_future", "orders_without_items", "possible_duplicates"}
    assert got["received_before_created"].severity == "warning" and got["received_before_created"].count == 2
    assert "NOT removed" in got["possible_duplicates"].message           # duplicates are flagged, never deleted
    assert got["awaiting_receipt"].severity == "info"
