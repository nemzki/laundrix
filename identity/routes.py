from flask import (
    abort, current_app, flash, jsonify, redirect, render_template, request, url_for,
)
from flask_login import current_user, login_required

from app.extensions import csrf, limiter
from app.identity import bp, services
from app.identity.signature import WebhookError, parse_json_object, verify_signature_v2
from app.identity.statuses import STATUS_COPY, CATEGORY_HINTS, IdvStatus, reason_category


@bp.before_request
def _feature_gate():
    """The whole feature is a 404 until IDV_ENABLED=true (keeps existing deployments unchanged)."""
    if not current_app.config["IDV_ENABLED"]:
        abort(404)


@bp.app_context_processor
def _inject_summary():
    def idv_summary():
        if not current_app.config["IDV_ENABLED"] or not current_user.is_authenticated:
            return None
        return services.summary_for(current_user)
    return {"idv_summary": idv_summary}


# ------------------------------------------------------------------------------ user pages
@bp.route("/")
@login_required
def index():
    ctx = services.summary_for(current_user)
    return render_template(
        "identity/status.html", history=services.history_for(current_user), is_latest=True, **ctx
    )


@bp.route("/attempt/<public_id>")
@login_required
def attempt(public_id):
    """One past attempt. Looked up by (public_id AND current user): other people's give a 404."""
    v = services.get_owned_verification(current_user, public_id, purpose=services.PURPOSE_KYC)
    if v is None:
        abort(404)
    copy = STATUS_COPY[v.status]
    hint = None
    if v.status in (IdvStatus.REJECTED, IdvStatus.ACTION_REQUIRED) and v.reason_codes:
        hint = CATEGORY_HINTS[reason_category(v.reason_codes)]
    return render_template(
        "identity/status.html", status=v.status, ui=copy, hint=hint, verification=v,
        can_start=False, can_refresh=False, blocked_message=None, history=[], is_latest=False,
    )


@bp.route("/start", methods=["GET", "POST"])
@limiter.limit("5 per minute; 20 per hour", methods=["POST"])
@login_required
def start():
    if request.method == "POST":
        result = services.start_verification(current_user, request.form.get("consent") == "on")
        if result.redirect_url:
            return redirect(result.redirect_url)  # hosted page; URL host was validated in the provider
        flash(result.message, "error" if result.error in ("consent_required",) else "info")
        if result.error == "consent_required":
            return redirect(url_for("identity.start"))
        return redirect(url_for("identity.index"))

    block = services.start_block_reason(current_user)
    if block:
        flash(services.START_MESSAGES[block], "info")
        return redirect(url_for("identity.index"))
    return render_template("identity/consent.html")


@bp.route("/return")
@login_required
@limiter.limit("20 per minute")
def return_from_provider():
    """Where the provider sends the user afterwards.

    The query string it appends (session id / status) is attacker-controllable, so it is IGNORED.
    The result comes from the signed webhook or a server-side call to the provider's API.
    """
    v = services.latest_verification(current_user)
    if v is not None:
        result = services.reconcile(v)
        if result.outcome == "provider_error":
            flash("We're still waiting for your result. This page will update shortly.", "info")
        else:
            flash("Thanks! Here's your current verification status.", "info")
    return redirect(url_for("identity.index"))


@bp.route("/refresh", methods=["POST"])
@login_required
@limiter.limit("10 per minute")
def refresh():
    v = services.latest_verification(current_user)
    if v is not None:
        result = services.reconcile(v)
        if result.outcome == "cooldown":
            flash("Just checked. Please wait a few seconds before checking again.", "info")
        elif result.outcome == "provider_error":
            flash("We couldn't reach the verification service. Your status hasn't changed.", "info")
    return redirect(url_for("identity.index"))


# ------------------------------------------------------------------------------ webhook
@bp.route("/webhook/didit", methods=["POST"])
@csrf.exempt  # authenticated by an HMAC signature instead of a browser CSRF token
@limiter.limit("120 per minute")
def didit_webhook():
    cfg = current_app.config
    raw = request.get_data(cache=False)  # size already capped by MAX_CONTENT_LENGTH

    try:
        payload = parse_json_object(raw)
    except WebhookError as exc:
        current_app.logger.warning("Rejected Didit webhook (%s) from %s", exc.reason, request.remote_addr)
        return jsonify(error="bad_request"), 400
    try:
        verify_signature_v2(
            payload,
            request.headers.get("X-Signature-V2"),
            request.headers.get("X-Timestamp"),
            cfg["DIDIT_WEBHOOK_SECRET"],
        )
    except WebhookError as exc:
        current_app.logger.warning("Rejected Didit webhook (%s) from %s", exc.reason, request.remote_addr)
        return jsonify(error="unauthorized"), 401

    # Console "Try Webhook" deliveries are signed but synthetic: acknowledge, never apply.
    if request.headers.get("X-Didit-Test-Webhook", "").lower() == "true":
        return jsonify(ok=True, ignored="test_delivery"), 200

    outcome = services.process_webhook(payload)  # exceptions -> 500 -> provider retries
    current_app.logger.info("Didit webhook processed: %s", outcome)
    return jsonify(ok=True), 200
