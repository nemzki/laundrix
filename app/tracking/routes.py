from flask import abort, render_template

from app.models import Order
from app.tracking import bp


@bp.get("/track/<token>")
def view_order(token):
    if not token or len(token) > 64:
        abort(404)

    order = Order.query.filter_by(tracking_token=token).first()

    if order is None:
        abort(404)

    return render_template("tracking/order.html", order=order)