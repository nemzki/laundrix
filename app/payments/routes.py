"""Payment administration endpoints.

DEFAULT-DENY: every route in this blueprint is Admin-only unless its view is explicitly marked
`@staff_allowed`. (Recording a payment against an order lives in the orders blueprint, which already
permits Staff and Admin.) Stage 3 exposes JSON/redirect actions; the admin pages arrive in Stage 6."""
from datetime import date

from flask import (
    Response, abort, current_app, flash, jsonify, redirect, render_template, request, url_for,
)
from flask_login import current_user

from app.core.timeutil import local_day_bounds_utc, period_bounds_utc
from app.extensions import db
from app.models import Order, Payment, PaymentKind, PaymentMethod, PaymentSettings, Role, User
from app.payments import bp, forms, services, uploads


def staff_allowed(view):
    view.staff_allowed = True
    return view


@bp.before_request
def _default_deny():
    if request.endpoint is None:          # unknown URL/method: let Flask answer 404/405
        return None
    if not current_user.is_authenticated:
        return current_app.login_manager.unauthorized()
    if not current_user.is_active:
        abort(403)
    view = current_app.view_functions.get(request.endpoint)
    if getattr(view, "staff_allowed", False):
        if current_user.role in (Role.ADMIN, Role.STAFF):
            return None
        abort(403)
    if current_user.role != Role.ADMIN:
        abort(403)
    return None


def _json(ok, status=200, **extra):
    return jsonify(ok=ok, **extra), status


# ----------------------------------------------------------------------------- report pages
PAGE_SIZE = 15


def _parse_day(text):
    try:
        return date.fromisoformat((text or "").strip())
    except ValueError:
        return None


@bp.get("/")
def records():
    """Every ledger entry (Admin). Filter by method, recorded-by, kind and date."""
    method = request.args.get("method", "")
    staff_id = request.args.get("staff", type=int)
    kind = request.args.get("kind", "")
    d_from, d_to = _parse_day(request.args.get("from")), _parse_day(request.args.get("to"))
    page = max(request.args.get("page", 1, type=int), 1)

    q = db.select(Payment).join(Order, Order.id == Payment.order_id)
    if method:
        q = q.where(Payment.method_code == method)
    if staff_id:
        q = q.where(Payment.recorded_by_id == staff_id)
    if kind in PaymentKind.ALL:
        q = q.where(Payment.kind == kind)
    if d_from:
        q = q.where(Payment.paid_at >= local_day_bounds_utc(d_from)[0])
    if d_to:
        q = q.where(Payment.paid_at < local_day_bounds_utc(d_to)[1])
    pagination = db.paginate(q.order_by(Payment.paid_at.desc(), Payment.id.desc()),
                             page=page, per_page=PAGE_SIZE, error_out=False)
    return render_template(
        "payments/records.html", pagination=pagination, payments=pagination.items,
        methods=db.session.scalars(db.select(PaymentMethod).order_by(PaymentMethod.sort_order)).all(),
        staff=db.session.scalars(db.select(User).where(User.role.in_([Role.ADMIN, Role.STAFF])).order_by(User.email)).all(),
        f={"method": method, "staff": staff_id, "kind": kind,
           "from": d_from.isoformat() if d_from else "", "to": d_to.isoformat() if d_to else ""},
    )


@bp.get("/outstanding")
@staff_allowed
def outstanding():
    """Orders by derived payment status. Staff and Admin may see balances; 'paid' is Admin-only."""
    status = request.args.get("status", "outstanding")
    if status not in services.OUTSTANDING_FILTERS:
        status = "outstanding"
    if status == "paid" and current_user.role != Role.ADMIN:
        abort(403)
    page = max(request.args.get("page", 1, type=int), 1)
    pagination = db.paginate(services.orders_by_payment_status(status), page=page,
                             per_page=PAGE_SIZE, error_out=False)
    count, balance = services.outstanding_summary()
    return render_template("payments/outstanding.html", pagination=pagination, orders=pagination.items,
                           status=status, owing_count=count, owing_total=balance)


@bp.get("/summary")
def summary():
    """Collections for today / this week / this month (Admin). Reversals subtract on the day recorded."""
    period = request.args.get("period", "daily")
    if period not in ("daily", "weekly", "monthly"):
        period = "daily"
    start, end, label = period_bounds_utc(period)
    totals = {p: services.collections_total(*period_bounds_utc(p)[:2]) for p in ("daily", "weekly", "monthly")}
    count, balance = services.outstanding_summary()
    return render_template(
        "payments/summary.html", period=period, label=label, totals=totals,
        by_method=services.collections_by_method(start, end), by_staff=services.collections_by_staff(start, end),
        collected=services.collections_total(start, end), owing_count=count, owing_total=balance,
    )


# ----------------------------------------------------------------------------- corrections
@bp.post("/<int:payment_id>/reverse")
def reverse(payment_id):
    body = forms.body_from_request(request)
    row, error = services.reverse_payment(payment_id, body.get("reason"), current_user)
    if request.is_json:
        return _json(error is None, 200 if error is None else 422,
                     **({"error": error} if error else {"reversal_id": row.id}))
    if error:
        flash(error, "error")
        original = db.session.get(Payment, payment_id)
        return redirect(url_for("orders.detail", reference=original.order.reference)) if original else abort(404)
    flash("Payment reversed. The original entry is kept in the history.", "success")
    return redirect(url_for("orders.detail", reference=row.order.reference))


# ----------------------------------------------------------------------------- settings page + actions
def _is_ui():
    """HTML form posts from the settings page carry ui=1; everything else gets JSON."""
    return (not request.is_json) and request.form.get("ui") == "1"


def _settings_context(values=None, errors=None):
    s = services.get_settings()
    base = {k: getattr(s, k) for k in (
        "partial_enabled", "pay_later_enabled", "gcash_account_name", "gcash_account_number",
        "payment_instructions", "payment_notice", "stub_footer", "show_qr_on_stub")}
    return dict(
        settings=s, values=values if values is not None else base, errors=errors or {},
        methods=db.session.scalars(db.select(PaymentMethod).order_by(PaymentMethod.sort_order, PaymentMethod.id)).all(),
    )


def _back(ok, message):
    flash(message, "success" if ok else "error")
    return redirect(url_for("payments.settings"))


@bp.get("/settings")
def settings():
    return render_template("payments/settings.html", **_settings_context())


@bp.post("/settings")
def update_settings():
    data = forms.body_from_request(request)
    saved, errors = services.update_settings(data, current_user)
    if _is_ui():
        if errors:
            flash("Please fix the highlighted fields.", "error")
            return render_template("payments/settings.html", **_settings_context(data, errors)), 422
        return _back(True, "Payment settings saved.")
    return _json(not errors, 200 if not errors else 422, errors=errors)


@bp.post("/methods")
def create_method():
    body = forms.body_from_request(request)
    method, error = services.create_method(body.get("label"), body.get("requires_reference"), current_user)
    if _is_ui():
        return _back(error is None, error or f"Added {method.label}.")
    return _json(error is None, 200 if error is None else 422,
                 **({"error": error} if error else {"id": method.id, "code": method.code}))


@bp.post("/methods/<int:method_id>/toggle")
def toggle_method(method_id):
    method, error = services.toggle_method(method_id, current_user)
    if _is_ui():
        return _back(error is None, error or f"{method.label} {'enabled' if method.is_active else 'disabled'}.")
    return _json(error is None, 200 if error is None else 422,
                 **({"error": error} if error else {"active": method.is_active}))


# ----------------------------------------------------------------------------- QR image
_PLACEHOLDER_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" width="240" height="240" viewBox="0 0 240 240" role="img" '
    'aria-label="Payment QR not set"><rect width="240" height="240" fill="#f4f7fb"/>'
    '<rect x="20" y="20" width="200" height="200" rx="12" fill="none" stroke="#94a3b8" '
    'stroke-width="3" stroke-dasharray="10 8"/>'
    '<text x="120" y="116" text-anchor="middle" font-family="Arial, sans-serif" font-size="16" '
    'fill="#475569">Payment QR</text><text x="120" y="140" text-anchor="middle" '
    'font-family="Arial, sans-serif" font-size="13" fill="#64748b">not uploaded yet</text></svg>'
)


@bp.get("/qr")
@staff_allowed
def qr():
    """Serves the configured payment QR (or a neutral placeholder). Fixed route: no path input."""
    path = uploads.qr_path(services.get_settings().qr_filename)
    data = None
    if path is not None:
        try:
            # Read into memory and close at once: holding the file open (send_file) would stop
            # Windows from deleting the old image when an Admin replaces it.
            data = path.read_bytes()
        except OSError:
            data = None
    if data is None:
        response = Response(_PLACEHOLDER_SVG, mimetype="image/svg+xml")
    else:
        response = Response(data, mimetype="image/png")
    response.headers["Cache-Control"] = "private, no-cache"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


@bp.post("/settings/qr")
def upload_qr():
    name, error = uploads.save_qr_image(request.files.get("image"))
    if error:
        if _is_ui():
            return _back(False, error)
        return _json(False, 422, error=error)
    settings = services.get_settings()
    old = settings.qr_filename
    settings.qr_filename = name
    settings.updated_by_id = current_user.id
    services.log_event("qr_uploaded", current_user, detail="Payment QR image replaced")
    db.session.commit()
    uploads.delete_qr(old)
    if _is_ui():
        return _back(True, "Payment QR image replaced.")
    return _json(True)


@bp.post("/settings/qr/remove")
def remove_qr():
    settings = services.get_settings()
    old, settings.qr_filename = settings.qr_filename, None
    settings.updated_by_id = current_user.id
    services.log_event("qr_removed", current_user, detail="Payment QR image removed")
    db.session.commit()
    uploads.delete_qr(old)
    if _is_ui():
        return _back(True, "Payment QR image removed.")
    return _json(True)
