"""Date ranges for Analytics, in Philippine business time.

Rules (see docs): the user picks *local* calendar dates; we convert them to
naive-UTC bounds (inclusive start, exclusive end) because that is how the
database stores timestamps.  Pure module: no Flask, no database.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from app.core.timeutil import SHOP_TZ, local_day_bounds_utc

PRESET_LABELS = {
    "today": "Today",
    "last_7": "Last 7 days",
    "last_30": "Last 30 days",
    "this_month": "This month",
    "last_month": "Last month",
    "custom": "Custom range",
}
DEFAULT_PRESET = "last_30"
MAX_RANGE_DAYS = 366
MIN_DATE = date(2020, 1, 1)
GRANULARITIES = ("day", "week", "month")

_ISO = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_EN_DASH = "\u2013"


class RangeError(ValueError):
    """A user-supplied date filter is invalid (message is safe to show)."""


def shop_today() -> date:
    return datetime.now(SHOP_TZ).date()


def _prev_month_bounds(d: date) -> tuple[date, date]:
    last = d.replace(day=1) - timedelta(days=1)
    return last.replace(day=1), last


@dataclass(frozen=True)
class DateRange:
    """Local dates, both inclusive.  ``preset`` drives the comparison rule."""

    start: date
    end: date
    preset: str = "custom"

    @property
    def days(self) -> int:
        return (self.end - self.start).days + 1

    @property
    def start_utc(self) -> datetime:
        return local_day_bounds_utc(self.start)[0]

    @property
    def end_utc(self) -> datetime:
        """Exclusive upper bound (start of the day after ``end``)."""
        return local_day_bounds_utc(self.end)[1]

    @property
    def label(self) -> str:
        if self.start == self.end:
            return f"{self.start:%b %d, %Y}"
        return f"{self.start:%b %d, %Y} {_EN_DASH} {self.end:%b %d, %Y}"

    def previous(self) -> "DateRange":
        """The comparison period.

        * last_month  -> the calendar month before it
        * this_month  -> same number of days from the start of the previous
                         month (month-to-date vs month-to-date; a partial
                         month is never compared with a full one)
        * anything else -> the immediately preceding window of equal length
        """
        if self.preset == "last_month":
            s, e = _prev_month_bounds(self.start)
        elif self.preset == "this_month":
            s, pm_end = _prev_month_bounds(self.start)
            e = min(s + timedelta(days=self.days - 1), pm_end)
        else:
            e = self.start - timedelta(days=1)
            s = e - timedelta(days=self.days - 1)
        return DateRange(s, e, "previous")

    def as_dict(self) -> dict:
        prev = self.previous()
        return {
            "preset": self.preset,
            "preset_label": PRESET_LABELS.get(self.preset, "Previous period"),
            "label": self.label,
            "start": self.start.isoformat(),
            "end": self.end.isoformat(),
            "days": self.days,
            "previous": {
                "label": prev.label,
                "start": prev.start.isoformat(),
                "end": prev.end.isoformat(),
                "days": prev.days,
            },
        }


def _parse(value: str, which: str) -> date:
    if not value:
        raise RangeError(f"Enter a {which} date.")
    if not _ISO.match(value):
        raise RangeError("Dates must use the YYYY-MM-DD format.")
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise RangeError(f"The {which} date is not a real calendar date.") from None


def resolve_range(preset=None, start=None, end=None, today: date | None = None) -> DateRange:
    """Validate request parameters and return a DateRange.

    ``today`` is injectable for tests.  Raises RangeError on bad input.
    A named preset wins over any start/end supplied alongside it.
    """
    today = today or shop_today()
    preset = (preset or "").strip().lower()
    start = (start or "").strip()
    end = (end or "").strip()
    if not preset:
        preset = "custom" if (start or end) else DEFAULT_PRESET
    if preset not in PRESET_LABELS:
        raise RangeError("Unknown date filter.")

    if preset == "today":
        return DateRange(today, today, preset)
    if preset == "last_7":
        return DateRange(today - timedelta(days=6), today, preset)
    if preset == "last_30":
        return DateRange(today - timedelta(days=29), today, preset)
    if preset == "this_month":
        return DateRange(today.replace(day=1), today, preset)
    if preset == "last_month":
        s, e = _prev_month_bounds(today)
        return DateRange(s, e, preset)

    s_date = _parse(start, "start")
    e_date = _parse(end, "end")
    if s_date > e_date:
        raise RangeError("The start date cannot be after the end date.")
    if s_date < MIN_DATE:
        raise RangeError(f"The start date cannot be before {MIN_DATE:%b %d, %Y}.")
    if e_date > today:
        raise RangeError("The end date cannot be in the future.")
    rng = DateRange(s_date, e_date, "custom")
    if rng.days > MAX_RANGE_DAYS:
        raise RangeError(f"Choose a range of {MAX_RANGE_DAYS} days or fewer.")
    return rng


def default_granularity(days: int) -> str:
    if days <= 31:
        return "day"
    if days <= 180:
        return "week"
    return "month"


def clean_granularity(value, rng: DateRange) -> str:
    value = (value or "").strip().lower()
    if not value:
        return default_granularity(rng.days)
    if value not in GRANULARITIES:
        raise RangeError("Granularity must be day, week or month.")
    return value
