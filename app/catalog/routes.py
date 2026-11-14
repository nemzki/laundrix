from flask import abort, current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user

from app.audit import services as audit
from app.catalog import bp, forms
from app.extensions import db
from app.models import (
    ICON_KEYS, PackageMeasure, PricingUnit, Role, Service, ServiceAddon, ServicePackage,
)


@bp.before_request
def _admin_only():
    """Backend authorization for EVERY catalog route: Admin only. Hidden links are not the control."""
    if not current_user.is_authenticated:
        return current_app.login_manager.unauthorized()
    if current_user.role != Role.ADMIN or not current_user.is_active:
        abort(403)


def _get_or_404(model, pk):
    obj = db.session.get(model, pk)
    if obj is None:
        abort(404)
    return obj


def _apply(obj, data):
    for key, value in data.items():
        setattr(obj, key, value)


# ---- audit trail (saved in the same transaction as the catalog change) ----------------------
# Only business fields are listed; image paths and icons are cosmetic and left out.
SERVICE_FIELDS = ("name", "category", "description", "price", "pricing_unit", "is_active")
PACKAGE_FIELDS = ("name", "category", "description", "size_label", "measure_type", "min_value",
                  "max_value", "price", "covers_codes", "is_active")
ADDON_FIELDS = ("name", "description", "price", "is_chargeable", "allow_customer_supplied", "is_active")


def _audit_label(kind, obj):
    return f"{kind.capitalize()}: {getattr(obj, 'display_name', None) or obj.name}"


def _audit_created(kind, obj, fields):
    db.session.flush()                                   # assigns obj.id for the audit record
    audit.record(audit.AuditAction.CREATE, audit.AuditModule.SERVICES,
                 f"Created {kind} {getattr(obj, 'display_name', None) or obj.name}",
                 resource_id=obj.id, resource_label=_audit_label(kind, obj),
                 new=audit.snapshot(obj, fields))


def _audit_edited(kind, obj, before, fields):
    old, new = audit.changes(before, audit.snapshot(obj, fields))
    if not new:
        return
    name = getattr(obj, "display_name", None) or obj.name
    if "price" in new:
        action = audit.AuditAction.PRICE_CHANGE
        text = f"Changed price of {kind} {name} from \u20b1{old['price']} to \u20b1{new['price']}"
    else:
        action, text = audit.AuditAction.UPDATE, f"Updated {kind} {name}"
    audit.record(action, audit.AuditModule.SERVICES, text, resource_id=obj.id,
                 resource_label=_audit_label(kind, obj), old=old, new=new)


def _audit_toggled(kind, obj):
    on = bool(obj.is_active)
    audit.record(audit.AuditAction.REACTIVATE if on else audit.AuditAction.DEACTIVATE,
                 audit.AuditModule.SERVICES,
                 f"{'Activated' if on else 'Deactivated'} {kind} {getattr(obj, 'display_name', None) or obj.name}",
                 resource_id=obj.id, resource_label=_audit_label(kind, obj),
                 old={"is_active": not on}, new={"is_active": on})


@bp.route("/")
def index():
    tab = request.args.get("tab", "services")
    if tab not in ("services", "packages", "addons"):
        tab = "services"
    return render_template(
        "catalog/index.html", tab=tab,
        services=db.session.scalars(db.select(Service).order_by(Service.is_active.desc(), Service.id)).all(),
        packages=db.session.scalars(
            db.select(ServicePackage).order_by(ServicePackage.category, ServicePackage.min_value)
        ).all(),
        addons=db.session.scalars(db.select(ServiceAddon).order_by(ServiceAddon.id)).all(),
    )


def _form_ctx(**extra):
    return dict(icon_keys=ICON_KEYS, units=PricingUnit, measures=PackageMeasure, **extra)


# ----------------------------------------------------------------------------- services
@bp.route("/services/new", methods=["GET", "POST"])
def service_new():
    if request.method == "POST":
        data, errors = forms.parse_service(request.form)
        if not errors:
            obj = Service(**data)
            db.session.add(obj)
            _audit_created("service", obj, SERVICE_FIELDS)
            db.session.commit()
            flash("Service created.", "success")
            return redirect(url_for("catalog.index", tab="services"))
        return render_template("catalog/service_form.html", obj=None, values=request.form,
                               errors=errors, **_form_ctx()), 422
    return render_template("catalog/service_form.html", obj=None,
                           values={"is_active": "on", "category": "Laundry service"}, errors={}, **_form_ctx())


@bp.route("/services/<int:pk>/edit", methods=["GET", "POST"])
def service_edit(pk):
    obj = _get_or_404(Service, pk)
    if request.method == "POST":
        data, errors = forms.parse_service(request.form, existing=obj)
        if not errors:
            before = audit.snapshot(obj, SERVICE_FIELDS)
            _apply(obj, data)
            _audit_edited("service", obj, before, SERVICE_FIELDS)
            db.session.commit()
            flash("Service updated. Existing orders keep the price they were charged.", "success")
            return redirect(url_for("catalog.index", tab="services"))
        return render_template("catalog/service_form.html", obj=obj, values=request.form,
                               errors=errors, **_form_ctx()), 422
    values = {
        "name": obj.name, "category": obj.category, "description": obj.description or "",
        "price": f"{obj.price:.2f}", "pricing_unit": obj.pricing_unit or "", "icon_key": obj.icon_key,
        "image_url": obj.image_url or "", "is_active": "on" if obj.is_active else "",
    }
    return render_template("catalog/service_form.html", obj=obj, values=values, errors={}, **_form_ctx())


@bp.post("/services/<int:pk>/toggle")
def service_toggle(pk):
    obj = _get_or_404(Service, pk)
    obj.is_active = not obj.is_active
    _audit_toggled("service", obj)
    db.session.commit()
    flash(f"{obj.name} {'activated' if obj.is_active else 'deactivated'}.", "success")
    return redirect(url_for("catalog.index", tab="services"))


# ----------------------------------------------------------------------------- packages
@bp.route("/packages/new", methods=["GET", "POST"])
def package_new():
    all_services = db.session.scalars(db.select(Service).order_by(Service.id)).all()
    if request.method == "POST":
        data, errors = forms.parse_package(request.form)
        if not errors:
            obj = ServicePackage(**data)
            db.session.add(obj)
            _audit_created("package", obj, PACKAGE_FIELDS)
            db.session.commit()
            flash("Package created.", "success")
            return redirect(url_for("catalog.index", tab="packages"))
        return render_template("catalog/package_form.html", obj=None, values=request.form, errors=errors,
                               all_services=all_services, covers=set(request.form.getlist("covers_codes")),
                               **_form_ctx()), 422
    values = {"is_active": "on", "name": "Wash, Dry & Fold", "measure_type": "weight"}
    return render_template("catalog/package_form.html", obj=None, values=values, errors={},
                           all_services=all_services, covers={"wash", "dry", "fold"}, **_form_ctx())


@bp.route("/packages/<int:pk>/edit", methods=["GET", "POST"])
def package_edit(pk):
    obj = _get_or_404(ServicePackage, pk)
    all_services = db.session.scalars(db.select(Service).order_by(Service.id)).all()
    if request.method == "POST":
        data, errors = forms.parse_package(request.form, existing=obj)
        if not errors:
            before = audit.snapshot(obj, PACKAGE_FIELDS)
            _apply(obj, data)
            _audit_edited("package", obj, before, PACKAGE_FIELDS)
            db.session.commit()
            flash("Package updated. Existing orders keep the price they were charged.", "success")
            return redirect(url_for("catalog.index", tab="packages"))
        return render_template("catalog/package_form.html", obj=obj, values=request.form, errors=errors,
                               all_services=all_services, covers=set(request.form.getlist("covers_codes")),
                               **_form_ctx()), 422
    values = {
        "name": obj.name, "category": obj.category, "description": obj.description,
        "size_label": obj.size_label or "", "measure_type": obj.measure_type,
        "min_value": f"{obj.min_value:f}".rstrip("0").rstrip("."), "max_value": f"{obj.max_value:f}".rstrip("0").rstrip("."),
        "price": f"{obj.price:.2f}", "icon_key": obj.icon_key, "image_url": obj.image_url or "",
        "is_active": "on" if obj.is_active else "",
    }
    return render_template("catalog/package_form.html", obj=obj, values=values, errors={},
                           all_services=all_services, covers=obj.covered_codes, **_form_ctx())


@bp.post("/packages/<int:pk>/toggle")
def package_toggle(pk):
    obj = _get_or_404(ServicePackage, pk)
    obj.is_active = not obj.is_active
    _audit_toggled("package", obj)
    db.session.commit()
    flash(f"{obj.display_name} {'activated' if obj.is_active else 'deactivated'}.", "success")
    return redirect(url_for("catalog.index", tab="packages"))


# ----------------------------------------------------------------------------- add-ons
@bp.route("/addons/new", methods=["GET", "POST"])
def addon_new():
    if request.method == "POST":
        data, errors = forms.parse_addon(request.form)
        if not errors:
            obj = ServiceAddon(**data)
            db.session.add(obj)
            _audit_created("extra", obj, ADDON_FIELDS)
            db.session.commit()
            flash("Extra created.", "success")
            return redirect(url_for("catalog.index", tab="addons"))
        return render_template("catalog/addon_form.html", obj=None, values=request.form,
                               errors=errors, **_form_ctx()), 422
    values = {"is_active": "on", "is_chargeable": "on", "allow_customer_supplied": "on"}
    return render_template("catalog/addon_form.html", obj=None, values=values, errors={}, **_form_ctx())


@bp.route("/addons/<int:pk>/edit", methods=["GET", "POST"])
def addon_edit(pk):
    obj = _get_or_404(ServiceAddon, pk)
    if request.method == "POST":
        data, errors = forms.parse_addon(request.form, existing=obj)
        if not errors:
            before = audit.snapshot(obj, ADDON_FIELDS)
            _apply(obj, data)
            _audit_edited("extra", obj, before, ADDON_FIELDS)
            db.session.commit()
            flash("Extra updated. Existing orders keep the price they were charged.", "success")
            return redirect(url_for("catalog.index", tab="addons"))
        return render_template("catalog/addon_form.html", obj=obj, values=request.form,
                               errors=errors, **_form_ctx()), 422
    values = {
        "name": obj.name, "description": obj.description or "", "price": f"{obj.price:.2f}",
        "icon_key": obj.icon_key, "image_url": obj.image_url or "",
        "is_chargeable": "on" if obj.is_chargeable else "",
        "allow_customer_supplied": "on" if obj.allow_customer_supplied else "",
        "is_active": "on" if obj.is_active else "",
    }
    return render_template("catalog/addon_form.html", obj=obj, values=values, errors={}, **_form_ctx())


@bp.post("/addons/<int:pk>/toggle")
def addon_toggle(pk):
    obj = _get_or_404(ServiceAddon, pk)
    obj.is_active = not obj.is_active
    _audit_toggled("extra", obj)
    db.session.commit()
    flash(f"{obj.name} {'activated' if obj.is_active else 'deactivated'}.", "success")
    return redirect(url_for("catalog.index", tab="addons"))
