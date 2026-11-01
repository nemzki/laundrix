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
