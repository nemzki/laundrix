"""HTTP layer for Analytics.  Handlers stay thin: validate, delegate, respond."""
from __future__ import annotations

from urllib.parse import urlencode

from flask import abort, current_app, flash, jsonify, render_template, request
from flask_login import current_user

from app.analytics import bp, services
from app.analytics.periods import (
    DEFAULT_PRESET, MIN_DATE, PRESET_LABELS, RangeError, clean_granularity, resolve_range, shop_today,
)
from app.models import Role


@bp.before_request
def _admin_only():
    """Default-deny guard for EVERY route in this blueprint (pages, JSON, static,
    and anything added later).  Anonymous -> normal login redirect; non-admin -> 403."""
    if not current_user.is_authenticated:
        return current_app.login_manager.unauthorized()
    if current_user.role != Role.ADMIN:
        abort(403)
    return None


@bp.after_request
def _no_store(response):
    if response.mimetype == "application/json":
        response.headers["Cache-Control"] = "private, no-store"
    return response


def _range_from_request():
    return resolve_range(request.args.get("range"), request.args.get("start"), request.args.get("end"))


def _query_for(rng) -> str:
    """Canonical query string for the validated range (what the page's JS re-sends)."""
    if rng.preset == "custom":
        return urlencode({"range": "custom", "start": rng.start.isoformat(), "end": rng.end.isoformat()})
    return urlencode({"range": rng.preset})


@bp.get("/")
def index():
    try:
        rng = _range_from_request()
    except RangeError as exc:
        flash(str(exc), "error")
        rng = resolve_range(DEFAULT_PRESET)
    overview = services.build_overview(rng)
    return render_template(
        "analytics/index.html",
        rng=rng,
        period=overview["period"],
        presets=PRESET_LABELS,
        kpis=services.present_kpis(overview["kpis"]),
        query=_query_for(rng),
        today_iso=shop_today().isoformat(),
        min_date_iso=MIN_DATE.isoformat(),
    )


@bp.get("/api/overview")
def api_overview():
    try:
        rng = _range_from_request()
    except RangeError as exc:
        return jsonify(error=str(exc)), 400
    return jsonify(services.build_overview(rng))


@bp.get("/api/<section>")
def api_section(section):
    builder = services.SECTIONS.get(section)
    if builder is None:
        abort(404)
    try:
        rng = _range_from_request()
        granularity = clean_granularity(request.args.get("granularity"), rng)
    except RangeError as exc:
        return jsonify(error=str(exc)), 400
    return jsonify(builder(rng, granularity))
