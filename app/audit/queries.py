"""Audit-log filtering. Every filter becomes part of the SQL query (nothing is filtered in Python
or in the browser) and every input is validated against a whitelist or a strict format."""
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone

from app.audit.services import AuditAction, AuditModule
from app.core.timeutil import SHOP_TZ, local_day_bounds_utc
from app.extensions import db
from app.models import AuditLog

PAGE_SIZE = 10
MAX_PAGE = 100_000
STATUSES = {"success": True, "failed": False}
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")


@dataclass
class AuditFilters:
    q: str = ""            # staff / admin name
    action: str = ""
    module: str = ""
    status: str = ""       # "success" | "failed" | ""
    day: str = ""          # one shop-local calendar day, YYYY-MM-DD
    start: str = ""        # YYYY-MM-DDTHH:MM (or just a date), shop-local time
    end: str = ""
    lower: datetime = None  # parsed bounds as naive UTC: lower inclusive, upper exclusive
    upper: datetime = None
    notices: list = field(default_factory=list)

    @property
    def params(self) -> dict:
        """The active filters as URL parameters (used by the pagination links)."""
        pairs = (("q", self.q), ("action", self.action), ("module", self.module),
                 ("status", self.status), ("day", self.day), ("start", self.start), ("end", self.end))
        return {key: value for key, value in pairs if value}

    @property
    def active(self) -> bool:
        return bool(self.params)


def _to_utc(local_dt: datetime) -> datetime:
    return local_dt.astimezone(timezone.utc).replace(tzinfo=None)


def _parse_local(text):
    """-> (aware shop-local datetime, date_only) or None. Years outside 2000-2100 are refused."""
    text = (text or "").strip()
    for fmt, date_only in (("%Y-%m-%dT%H:%M", False), ("%Y-%m-%dT%H:%M:%S", False),
                           ("%Y-%m-%d %H:%M", False), ("%Y-%m-%d", True)):
        try:
            parsed = datetime.strptime(text, fmt)
        except ValueError:
            continue
        if 2000 <= parsed.year <= 2100:
            return parsed.replace(tzinfo=SHOP_TZ), date_only
    return None


def parse_filters(args) -> AuditFilters:
    """Build validated filters from request.args. Bad values are ignored and reported in `notices`."""
    f = AuditFilters()
    f.q = _CONTROL.sub("", (args.get("q") or "")).strip()[:100]

    action = (args.get("action") or "").strip()
    if action:
        if action in AuditAction.ALL:
            f.action = action
        else:
            f.notices.append("The action filter was not recognised and was ignored.")
    module = (args.get("module") or "").strip()
    if module:
        if module in AuditModule.ALL:
            f.module = module
        else:
            f.notices.append("The module filter was not recognised and was ignored.")
    status = (args.get("status") or "").strip()
    if status:
        if status in STATUSES:
            f.status = status
        else:
            f.notices.append("The result filter was not recognised and was ignored.")

    lowers, uppers = [], []
    day_text = (args.get("day") or "").strip()
    if day_text:
        parsed = _parse_local(day_text)
        if parsed and parsed[1]:
            f.day = day_text
            lo, hi = local_day_bounds_utc(parsed[0].date())
            lowers.append(lo)
            uppers.append(hi)
        else:
            f.notices.append("The day must be a valid date (YYYY-MM-DD) and was ignored.")
    for name in ("start", "end"):
        text = (args.get(name) or "").strip()
        if not text:
            continue
        parsed = _parse_local(text)
        if parsed is None:
            f.notices.append(f"The {name} date/time is not valid and was ignored.")
            continue
        local_dt, date_only = parsed
        setattr(f, name, text)
        if name == "start":
            lowers.append(_to_utc(local_dt))
        else:                                   # inclusive: up to the end of that minute / day
            uppers.append(_to_utc(local_dt + (timedelta(days=1) if date_only else timedelta(minutes=1))))

    f.lower = max(lowers) if lowers else None
    f.upper = min(uppers) if uppers else None
    if f.lower and f.upper and f.lower >= f.upper:
        f.notices.append("The date range is empty (the start is not before the end), so it was ignored.")
        f.lower = f.upper = None
        f.day = f.start = f.end = ""
    return f


def _like_escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("%", r"\%").replace("_", r"\_")


def build_query(f: AuditFilters):
    q = db.select(AuditLog)
    if f.q:
        q = q.where(AuditLog.actor_name.ilike(f"%{_like_escape(f.q)}%", escape="\\"))
    if f.action:
        q = q.where(AuditLog.action == f.action)
    if f.module:
        q = q.where(AuditLog.module == f.module)
    if f.status:
        q = q.where(AuditLog.success.is_(STATUSES[f.status]))
    if f.lower is not None:
        q = q.where(AuditLog.created_at >= f.lower)
    if f.upper is not None:
        q = q.where(AuditLog.created_at < f.upper)
    return q.order_by(AuditLog.created_at.desc(), AuditLog.id.desc())


def diff_rows(row):
    """[(field, before, after)] for the changed values stored on one audit row."""
    old = row.old_values if isinstance(row.old_values, dict) else {}
    new = row.new_values if isinstance(row.new_values, dict) else {}
    return [(key, old.get(key), new.get(key)) for key in dict.fromkeys([*old, *new])]


def page_number(args) -> int:
    try:
        return min(max(int(args.get("page", 1)), 1), MAX_PAGE)
    except (TypeError, ValueError):
        return 1
