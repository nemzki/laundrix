"""Admin-only analytics and reporting routes."""
from datetime import timedelta

from flask import Response, abort, flash, jsonify, redirect, render_template, request, stream_with_context, url_for
from flask_login import current_user, login_required
from sqlalchemy.exc import IntegrityError

from app.analytics import bp
from app.analytics import exports
from app.analytics.charts import PERIODS, parse_period
from app.analytics.ml.system_data import shop_today
from app.analytics.services import get_analytics_report
from app.audit import services as audit
from app.core.decorators import role_required
from app.extensions import db, limiter
from app.models import Order, OrderDisposal, OrderStatus, Role


@bp.route("/", endpoint="index")
@login_required
@role_required(Role.ADMIN)
def index():
    """Render the admin analytics and reports workspace."""
    days = parse_period(request.args.get("days"))
    today = shop_today()
    return render_template(
        "analytics/index.html",
        report=get_analytics_report(days),
        periods=PERIODS,
        days=days,
        export_datasets=exports.DATASETS,
        export_formats=exports.FORMATS,
        export_config=exports.ui_config(),
        export_defaults={
            "start": (today - timedelta(days=29)).isoformat(),
            "end": today.isoformat(),
        },
    )


def _parse_export_request():
    """Read and validate everything an export needs from the query string.

    Shared by the preview and the download so they can never disagree.
    Unknown dataset -> 404. Anything else invalid -> ExportError (message is safe to show).
    """
    dataset = request.args.get("dataset", "orders")
    if dataset not in exports.DATASETS:
        abort(404)
    fmt = exports.parse_format(request.args.get("format"))
    start, end = exports.parse_range(request.args.get("start"), request.args.get("end"), shop_today())
    filters = exports.parse_filters(dataset, request.args.getlist)

    keys = request.args.getlist("columns")
    if keys:
        columns = exports.resolve_columns(dataset, keys)
    elif request.args.get("custom"):          # the form was used but nothing was ticked
        raise exports.ExportError("Please tick at least one column to export.")
    else:                                      # old links / bookmarks: export the standard columns
        columns = exports.resolve_columns(dataset)
    return dataset, fmt, start, end, columns, filters


@bp.get("/export/preview", endpoint="export_preview")
@login_required
@role_required(Role.ADMIN)
@limiter.limit("60 per minute")
def export_preview():
    """How many rows would this export contain? (JSON for the live counter in the export form.)"""
    try:
        dataset, _fmt, start, end, _columns, filters = _parse_export_request()
    except exports.ExportError as exc:
        return jsonify(ok=False, error=str(exc)), 400
    rows = exports.count_rows(dataset, start, end, filters)
    return jsonify(ok=True, rows=rows, limit=exports.MAX_ROWS, too_many=rows > exports.MAX_ROWS)


@bp.get("/export", endpoint="export")
@login_required
@role_required(Role.ADMIN)
def export():
    """Download real records as a CSV or Excel file. Admin only; every export is written to the audit log."""
    try:
        dataset, fmt, start, end, columns, filters = _parse_export_request()
    except exports.ExportError as exc:
        flash(str(exc), "error")
        return redirect(url_for("analytics.index"))

    rows = exports.count_rows(dataset, start, end, filters)
    if rows > exports.MAX_ROWS:
        flash(f"That selection has {rows:,} rows; please choose a shorter range or add filters (limit {exports.MAX_ROWS:,}).", "error")
        return redirect(url_for("analytics.index"))
    if rows == 0:
        flash("There are no records that match that date range and those filters.", "info")
        return redirect(url_for("analytics.index"))

    details = f"{len(columns)} of {len(exports.COLUMNS[dataset])} columns"
    if filters.describe():
        details += f"; {filters.describe()}"
    audit.record(
        audit.AuditAction.EXPORT, audit.AuditModule.ORDERS,
        f"Exported {dataset} {exports.FORMATS[fmt]} ({rows} rows, {start} to {end}; {details})",
    )
    db.session.commit()

    filename = f"laundrix_{dataset}_{start.isoformat()}_to_{end.isoformat()}.{fmt}"
    if fmt == "xlsx":
        who = getattr(current_user, "full_name", None) or getattr(current_user, "email", "")
        response = Response(
            exports.xlsx_bytes(dataset, start, end, columns, filters, generated_by=who),
            mimetype=exports.XLSX_MIMETYPE,
        )
    else:
        response = Response(
            stream_with_context(exports.csv_stream(dataset, start, end, columns, filters)),
            mimetype="text/csv",
        )
        response.headers["Content-Type"] = "text/csv; charset=utf-8"
    response.headers["Content-Disposition"] = f'attachment; filename="{filename}"'
    response.headers["Cache-Control"] = "no-store"
    return response


@bp.post("/orders/<int:order_id>/dispose", endpoint="dispose")
@login_required
@role_required(Role.ADMIN)
def dispose(order_id):
    """Record that an unclaimed Ready-for-Pickup order was disposed of.

    Only writes to order_disposals (plus an audit row). The order's own status is not changed.
    """
    order = db.session.get(Order, order_id)
    if order is None:
        abort(404)
    if order.status != OrderStatus.READY:
        flash("Only orders that are Ready for Pickup can be marked as disposed.", "error")
    elif db.session.scalar(db.select(OrderDisposal.id).where(OrderDisposal.order_id == order.id)):
        flash(f"Order {order.reference} is already marked as disposed.", "info")
    else:
        try:
            db.session.add(OrderDisposal(order_id=order.id, disposed_by_id=current_user.id))
            audit.record(
                audit.AuditAction.UPDATE, audit.AuditModule.ORDERS,
                f"Marked unclaimed order {order.reference} as disposed",
                resource_id=order.id, resource_label=f"Order {order.reference}",
            )
            db.session.commit()
            flash(f"Order {order.reference} marked as disposed.", "success")
        except IntegrityError:  # double-click / two admins at once
            db.session.rollback()
            flash(f"Order {order.reference} is already marked as disposed.", "info")
    return redirect(url_for("analytics.index"))


@bp.post("/orders/<int:order_id>/undo-dispose", endpoint="undo_dispose")
@login_required
@role_required(Role.ADMIN)
def undo_dispose(order_id):
    """Remove a 'disposed' mark that was made by mistake."""
    disposal = db.session.scalar(db.select(OrderDisposal).where(OrderDisposal.order_id == order_id))
    if disposal is None:
        abort(404)
    reference = disposal.order.reference
    db.session.delete(disposal)
    audit.record(
        audit.AuditAction.UPDATE, audit.AuditModule.ORDERS,
        f"Undid the disposed mark on order {reference}",
        resource_id=order_id, resource_label=f"Order {reference}",
    )
    db.session.commit()
    flash(f"Disposed mark removed from order {reference}.", "success")
    return redirect(url_for("analytics.index"))
