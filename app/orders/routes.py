import secrets

from flask import abort, current_app, flash, jsonify, redirect, render_template, request, url_for
from flask_login import current_user

from app.core.decorators import role_required
from app.extensions import db
from app.models import Customer, Order, OrderStatus, Role, Service, ServiceAddon, ServicePackage
from app.orders import bp, services
from app.orders.pricing import build_quote
from app.payments import forms as payment_forms
from app.payments import services as payment_services
from app.tracking.qr import generate_qr_data_uri

@bp.before_request
def _require_operational_user():
    """Every route in this blueprint is for signed-in Admin or Staff only (backend enforced)."""
    if not current_user.is_authenticated:
        return current_app.login_manager.unauthorized()
    if current_user.role not in (Role.ADMIN, Role.STAFF) or not current_user.is_active:
        abort(403)


def _peso(value):
    return f"\u20b1{value:,.2f}"


def _get_order_or_404(reference):
    order = db.session.execute(db.select(Order).filter_by(reference=reference)).scalar_one_or_none()
    if order is None:
        abort(404)
    return order


# ----------------------------------------------------------------------------- list
@bp.route("/")
def index():
    term = request.args.get("q", "").strip()
    status = request.args.get("status", "")
    page = request.args.get("page", 1, type=int)
    pagination = db.paginate(
        services.order_query(term, status), page=max(page, 1), per_page=services.PAGE_SIZE, error_out=False
    )
    return render_template(
        "orders/index.html", pagination=pagination, orders=pagination.items,
        term=term, status=status, statuses=OrderStatus, counts=services.status_counts(),
    )


# ----------------------------------------------------------------------------- wizard
@bp.route("/new")
def new_order():
    svc = db.session.execute(
        db.select(Service).where(Service.is_active.is_(True)).order_by(Service.category, Service.id)
    ).scalars().all()
    pkgs = db.session.execute(
        db.select(ServicePackage).where(ServicePackage.is_active.is_(True))
        .order_by(ServicePackage.category, ServicePackage.min_value)
    ).scalars().all()
    addons = db.session.execute(
        db.select(ServiceAddon).where(ServiceAddon.is_active.is_(True)).order_by(ServiceAddon.id)
    ).scalars().all()
    package_groups = {}
    for p in pkgs:
        package_groups.setdefault(p.category, []).append(p)
    return render_template(
        "orders/new.html", services=svc, package_groups=package_groups, addons=addons,
        methods=payment_services.active_methods(), pay_settings=payment_services.get_settings(),
        submission_token=secrets.token_urlsafe(18),   # one per wizard load: a double-click saves one order
    )


@bp.post("/new/quote")
def quote():
    payload = request.get_json(silent=True)
    q = build_quote(payload)
    errors = {k: list(v) for k, v in q.errors.items()}
    duplicates = []
    if isinstance(payload, dict) and payload.get("require_customer"):
        _, _, cust_errors, duplicates = services.validate_customer(payload.get("customer"))
        errors.update(cust_errors)
    payment_preview = None
    if isinstance(payload, dict) and "payment" in payload and q.ok:
        plan = payment_services.validate_payment_plan(payload.get("payment"), q.total)
        errors.update(plan.errors)
        if not plan.errors:
            payment_preview = plan.preview()
    return jsonify(
        ok=not errors, errors=errors, duplicates=duplicates,
        payment=payment_preview, total_raw=str(q.total),
        lines=[{
            "key": l.key, "name": l.name, "description": l.description,
            "quantity": f"{l.quantity.normalize():f}", "unit": l.unit,
            "measurement": None if l.measurement is None else f"{l.measurement.normalize():f}",
            "measurement_unit": l.measurement_unit, "customer_supplied": l.customer_supplied,
            "instructions": l.instructions,
            "unit_price": _peso(l.unit_price), "line_total": _peso(l.line_total),
        } for l in q.lines],
        subtotal=_peso(q.subtotal), total=_peso(q.total),
    )


@bp.post("/new/confirm")
def confirm():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify(ok=False, errors={"_general": ["Invalid request."]}), 400
    order, errors, duplicates = services.create_order(payload, current_user)
    if errors:
        return jsonify(ok=False, errors=errors, duplicates=duplicates), 422
    return jsonify(ok=True, redirect=url_for("orders.confirmation", reference=order.reference))


@bp.get("/customers/search")
def customer_search():
    found = services.search_customers(request.args.get("q", ""))
    return jsonify(results=[
        {"id": c.id, "full_name": c.full_name, "contact_number": c.contact_number} for c in found
    ])


# ----------------------------------------------------------------------------- customers (admin)
@bp.route("/customers")
@role_required(Role.ADMIN)
def customers():
    term = request.args.get("q", "").strip()
    page = request.args.get("page", 1, type=int)
    q = db.select(Customer).order_by(Customer.full_name)
    if term:
        like = f"%{services._like_escape(term)}%"
        q = q.where(Customer.full_name.ilike(like, escape="\\") | Customer.contact_number.like(like))
    pagination = db.paginate(q, page=max(page, 1), per_page=services.PAGE_SIZE, error_out=False)
    return render_template("orders/customers.html", pagination=pagination, customers=pagination.items, term=term)


# ----------------------------------------------------------------------------- single order
@bp.route("/<reference>")
def detail(reference):
    order = _get_order_or_404(reference)
    return render_template(
        "orders/detail.html", order=order, transitions=services.allowed_transitions(order, current_user),
        statuses=OrderStatus, methods=payment_services.active_methods(),
        idempotency_key=secrets.token_urlsafe(12), is_admin=current_user.role == Role.ADMIN,
    )


@bp.route("/<reference>/confirmation")
def confirmation(reference):
    return render_template("orders/confirmation.html", order=_get_order_or_404(reference))


@bp.route("/<reference>/stub")
def stub(reference):
    order = _get_order_or_404(reference)

    tracking_path = url_for(
        "tracking.view_order",
        token=order.tracking_token,
    )
    tracking_url = current_app.config["APP_BASE_URL"] + tracking_path

    qr_code = generate_qr_data_uri(tracking_url)

    # Customer-facing payment summary: net per method. No references, no staff, no audit data.
    per_method = {}
    for p in order.payments:
        per_method[p.method_label] = per_method.get(p.method_label, 0) + (
            p.amount if p.kind == "payment" else -p.amount)
    payment_lines = [(label, amount) for label, amount in per_method.items() if amount != 0]
    cashier = None
    if order.created_by is not None:
        cashier = ((order.created_by.full_name or "").split() or ["Staff"])[0]

    return render_template(
        "orders/stub.html",
        order=order,
        tracking_url=tracking_url,
        qr_code=qr_code,
        payment_lines=payment_lines,
        cashier=cashier,
        pay_settings=payment_services.get_settings(),
    )

@bp.post("/<reference>/status")
def update_status(reference):
    order = _get_order_or_404(reference)
    updated, error = services.change_status(
        order.id, request.form.get("status", ""), current_user, request.form.get("note")
    )
    if error:
        flash(error, "error")
    else:
        flash(f"Status updated to {OrderStatus.LABELS[updated.status]}.", "success")
    return redirect(url_for("orders.detail", reference=reference))

@bp.post("/<reference>/payments")
def record_payment(reference):
    """Record a later payment (e.g. settling a balance). Amounts are validated against the live
    server-side balance; the browser's idea of the balance is never used."""
    order = _get_order_or_404(reference)
    entries, key = payment_forms.entries_from_request(request)
    if entries is None:
        payments, errors, duplicate = [], {"payment": ["Invalid request."]}, False
    else:
        payments, errors, duplicate = payment_services.record_payments(order.id, entries, current_user, key)
    if request.is_json:
        if errors:
            return jsonify(ok=False, errors=errors), 422
        return jsonify(
            ok=True, duplicate=duplicate, payment_ids=[p.id for p in payments],
            balance=payment_services.peso(order.balance_due), payment_status=order.payment_status,
        )
    if errors:
        for messages in errors.values():
            for m in messages:
                flash(m, "error")
    elif duplicate:
        flash("That payment was already recorded.", "info")
    else:
        flash("Payment recorded.", "success")
    return redirect(url_for("orders.detail", reference=reference))


@bp.post("/<reference>/confirm-received")
def confirm_received(reference):
    """Staff confirm the physical laundry was received. Independent of payment."""
    order = _get_order_or_404(reference)
    updated, error, already = services.confirm_received(order.id, current_user)
    if request.is_json:
        if error:
            return jsonify(ok=False, error=error), 422
        return jsonify(ok=True, already=already)
    if error:
        flash(error, "error")
    elif already:
        flash("The laundry was already confirmed as received.", "info")
    else:
        flash("Laundry confirmed as received.", "success")
    return redirect(url_for("orders.detail", reference=reference))

