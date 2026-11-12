"""Date-range rules.  Pure tests: no database."""
from datetime import date, datetime

from app.analytics.periods import (
    MAX_RANGE_DAYS, RangeError, clean_granularity, default_granularity, resolve_range,
)

TODAY = date(2026, 11, 7)  # a Saturday


def test_today_uses_philippine_midnight_boundaries():
    r = resolve_range("today", today=date(2026, 11, 3))
    # Nov 3 00:00 PHT is Nov 2 16:00 UTC; the range ends at Nov 4 00:00 PHT.
    assert r.start_utc == datetime(2026, 11, 2, 16, 0)
    assert r.end_utc == datetime(2026, 11, 3, 16, 0)


def test_last_7_and_30_are_inclusive_of_today():
    r7 = resolve_range("last_7", today=TODAY)
    assert (r7.start, r7.end, r7.days) == (date(2026, 11, 1), TODAY, 7)
    r30 = resolve_range("last_30", today=TODAY)
    assert (r30.start, r30.days) == (date(2026, 10, 9), 30)


def test_default_is_last_30():
    assert resolve_range(None, today=TODAY).preset == "last_30"


def test_this_month_and_last_month():
    r = resolve_range("this_month", today=TODAY)
    assert (r.start, r.end) == (date(2026, 11, 1), TODAY)
    r = resolve_range("last_month", today=TODAY)
    assert (r.start, r.end) == (date(2026, 10, 1), date(2026, 10, 31))


def test_last_month_across_year_boundary_and_leap_february():
    r = resolve_range("last_month", today=date(2026, 1, 15))
    assert (r.start, r.end) == (date(2025, 12, 1), date(2025, 12, 31))
    r = resolve_range("last_month", today=date(2024, 3, 10))
    assert (r.start, r.end) == (date(2024, 2, 1), date(2024, 2, 29))


def test_previous_period_for_rolling_ranges_is_equal_length_and_adjacent():
    r = resolve_range("last_7", today=TODAY)
    p = r.previous()
    assert (p.start, p.end) == (date(2026, 10, 25), date(2026, 10, 31))
    t = resolve_range("today", today=TODAY).previous()
    assert (t.start, t.end) == (date(2026, 11, 6), date(2026, 11, 6))


def test_previous_of_custom_10_day_range():
    r = resolve_range("custom", "2026-11-01", "2026-11-10", today=date(2026, 11, 20))
    p = r.previous()
    assert (p.start, p.end, p.days) == (date(2026, 10, 22), date(2026, 10, 31), 10)


def test_previous_of_last_month_is_the_month_before():
    p = resolve_range("last_month", today=TODAY).previous()
    assert (p.start, p.end) == (date(2026, 9, 1), date(2026, 9, 30))


def test_previous_of_this_month_is_month_to_date_of_previous_month():
    p = resolve_range("this_month", today=TODAY).previous()  # Nov 1-7 vs Oct 1-7
    assert (p.start, p.end) == (date(2026, 10, 1), date(2026, 10, 7))


def test_previous_of_this_month_is_clamped_to_shorter_month():
    p = resolve_range("this_month", today=date(2026, 3, 31)).previous()  # Mar 1-31 vs Feb
    assert (p.start, p.end) == (date(2026, 2, 1), date(2026, 2, 28))


def test_custom_range_valid():
    r = resolve_range("custom", "2026-10-01", "2026-10-15", today=TODAY)
    assert (r.start, r.end, r.days) == (date(2026, 10, 1), date(2026, 10, 15), 15)


def test_start_and_end_without_preset_means_custom():
    assert resolve_range(None, "2026-10-01", "2026-10-02", today=TODAY).preset == "custom"


def _bad(*args, message=None):
    try:
        resolve_range(*args, today=TODAY)
    except RangeError as exc:
        if message:
            assert message in str(exc)
        return
    raise AssertionError(f"expected RangeError for {args}")


def test_invalid_inputs_are_rejected():
    _bad("custom", "2026-13-01", "2026-13-02", message="real calendar date")
    _bad("custom", "2026-1-5", "2026-1-6", message="YYYY-MM-DD")
    _bad("custom", "not-a-date", "2026-10-02", message="YYYY-MM-DD")
    _bad("custom", "", "2026-10-02", message="start")
    _bad("custom", "2026-10-01", "", message="end")
    _bad("custom", "2026-10-05", "2026-10-01", message="cannot be after")
    _bad("custom", "2026-10-01", "2026-11-08", message="future")
    _bad("custom", "2019-12-31", "2020-01-02", message="before")
    _bad("bogus", message="Unknown")


def test_too_long_range_is_rejected_but_max_is_allowed():
    _bad("custom", "2025-01-01", "2026-11-07", message="days or fewer")
    # exactly MAX_RANGE_DAYS days is fine
    r = resolve_range("custom", "2025-11-07", "2026-11-07", today=TODAY)
    assert r.days == 366


def test_granularity_defaults_and_validation():
    assert default_granularity(7) == "day"
    assert default_granularity(60) == "week"
    assert default_granularity(300) == "month"
    r = resolve_range("last_7", today=TODAY)
    assert clean_granularity("", r) == "day"
    assert clean_granularity("WEEK", r) == "week"
    try:
        clean_granularity("hour", r)
    except RangeError:
        pass
    else:
        raise AssertionError("hour should be rejected")


def test_as_dict_is_json_friendly():
    d = resolve_range("last_7", today=TODAY).as_dict()
    assert d["start"] == "2026-11-01" and d["previous"]["end"] == "2026-10-31" and d["days"] == 7
