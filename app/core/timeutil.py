"""Display-time helpers. The database stores naive UTC; the shop operates in Philippine time
(UTC+8, no daylight saving), so a fixed offset is used and no tz database is required on Windows."""
from datetime import datetime, timedelta, timezone

SHOP_TZ = timezone(timedelta(hours=8))


def to_local(dt):
    if dt is None:
        return None
    return dt.replace(tzinfo=timezone.utc).astimezone(SHOP_TZ)


def local_today_bounds_utc():
    """(start, end) of the current shop day as naive UTC datetimes, for DB comparisons."""
    now_local = datetime.now(SHOP_TZ)
    start_local = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
    end_local = start_local + timedelta(days=1)
    to_utc = lambda d: d.astimezone(timezone.utc).replace(tzinfo=None)  # noqa: E731
    return to_utc(start_local), to_utc(end_local)


def local_date_code():
    return datetime.now(SHOP_TZ).strftime("%y%m%d")

def _to_utc_naive(d):
    return d.astimezone(timezone.utc).replace(tzinfo=None)


def local_day_bounds_utc(day):
    """(start, end) of a shop-local calendar date as naive UTC datetimes."""
    start = datetime(day.year, day.month, day.day, tzinfo=SHOP_TZ)
    return _to_utc_naive(start), _to_utc_naive(start + timedelta(days=1))


def period_bounds_utc(period):
    """(start, end, label) for the current shop-local day, week (Mon-Sun) or month."""
    today = datetime.now(SHOP_TZ).date()
    if period == "weekly":
        first = today - timedelta(days=today.weekday())
        last = first + timedelta(days=7)
        label = f"{first:%b %d} to {(last - timedelta(days=1)):%b %d, %Y}"
    elif period == "monthly":
        first = today.replace(day=1)
        last = (first.replace(year=first.year + 1, month=1) if first.month == 12
                else first.replace(month=first.month + 1))
        label = f"{first:%B %Y}"
    else:
        first, last = today, today + timedelta(days=1)
        label = f"{today:%b %d, %Y}"
    return local_day_bounds_utc(first)[0], local_day_bounds_utc(last)[0], label
