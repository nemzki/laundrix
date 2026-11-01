from flask import abort, current_app, flash, jsonify, redirect, render_template, request, url_for
from flask_login import current_user

from app.core.decorators import role_required
from app.extensions import db
from app.models import Customer, Order, OrderStatus, Role, Service, ServiceAddon, ServicePackage
from app.orders import bp, services
from app.orders.pricing import build_quote
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
    return jsonify(
        ok=not errors, errors=errors, duplicates=duplicates,
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
        statuses=OrderStatus,
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

    return render_template(
        "orders/stub.html",
        order=order,
        tracking_url=tracking_url,
        qr_code=qr_code,
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
