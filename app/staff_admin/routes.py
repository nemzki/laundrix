"""Admin-only Staff Management pages. Every route is wrapped in role_required(Role.ADMIN); the
lifecycle rules (and the "never your own account / never an admin" guards) live in services.py."""
from flask import abort, flash, make_response, redirect, render_template, request, url_for
from flask_login import current_user

from app.core.decorators import role_required
from app.extensions import db
from app.models import AccountStatus, Role, User
from app.staff_admin import bp, services
from app.staff_admin.services import ActionError

admin_only = role_required(Role.ADMIN)

FILTERS = [("", "All")] + [
    (AccountStatus.PENDING_VERIFICATION, "Pending verification"),
    (AccountStatus.PENDING_APPROVAL, "Pending approval"),
    (AccountStatus.ACTIVE, "Active"),
    (AccountStatus.SUSPENDED, "Suspended"),
    (AccountStatus.REJECTED, "Rejected"),
    (AccountStatus.DEACTIVATED, "Deactivated"),
]


def _staff_or_404(user_id):
    user = db.session.get(User, user_id)
    if user is None or user.role != Role.STAFF:
        abort(404)
    return user


def _no_store(response):
    """One-time secrets must never be cached or kept in history."""
    response.headers["Cache-Control"] = "no-store, no-cache, max-age=0"
    response.headers["Pragma"] = "no-cache"
    return response


@bp.route("/")
@admin_only
def index():
    status = request.args.get("status", "")
    term = request.args.get("q", "").strip()[:100]
    sort = request.args.get("sort", "newest")
    page = max(request.args.get("page", 1, type=int), 1)
    pagination = db.paginate(services.staff_query(status, term, sort), page=page,
                             per_page=services.PAGE_SIZE, error_out=False)
    rows = [(u, *services.identity_summary(u)[:2]) for u in pagination.items]
    return render_template(
        "staff_admin/index.html", rows=rows, pagination=pagination, counts=services.status_counts(),
        filters=FILTERS, status=status if status in AccountStatus.ALL else "", term=term,
        sort=sort if sort in services.SORTS else "newest", statuses=AccountStatus,
    )


@bp.route("/new", methods=["GET", "POST"])
@admin_only
def new():
    if request.method == "GET":
        return render_template("staff_admin/new.html", values={}, error=None)
    values = {"full_name": request.form.get("full_name", ""), "email": request.form.get("email", "")}
    try:
        user, url, expires = services.create_staff_account(values["full_name"], values["email"], current_user)
    except ActionError as exc:
        return render_template("staff_admin/new.html", values=values, error=str(exc)), 422
    # Rendered directly (never redirected, never stored): this response is the only place the link appears.
    return _no_store(make_response(render_template(
        "staff_admin/link.html", staff=user, enroll_url=url, expires=expires, replacement=False)))


@bp.route("/<int:user_id>")
@admin_only
def detail(user_id):
    user = _staff_or_404(user_id)
    label, tone, verification = services.identity_summary(user)
    cred = user.staff_credential
    from app.models.staff_credential import utcnow
    link_live = bool(cred and cred.enroll_token_hash and cred.enroll_token_expires_at
                     and cred.enroll_token_expires_at > utcnow())
    return render_template(
        "staff_admin/detail.html", staff=user, idv_label=label, idv_tone=tone, verification=verification,
        link_live=link_live, link_expires=cred.enroll_token_expires_at if link_live else None,
        approver=db.session.get(User, user.approved_by_id) if user.approved_by_id else None,
        changed_by=db.session.get(User, user.status_changed_by_id) if user.status_changed_by_id else None,
        activity=services.recent_activity(user), statuses=AccountStatus,
        can_approve=user.account_status == AccountStatus.PENDING_APPROVAL,
    )


def _act(user_id, success_message, fn, *args):
    _staff_or_404(user_id)
    try:
        fn(user_id, current_user, *args)
        flash(success_message, "success")
    except ActionError as exc:
        flash(str(exc), "error")
    return redirect(url_for("staff_admin.detail", user_id=user_id))


@bp.post("/<int:user_id>/approve")
@admin_only
def approve(user_id):
    return _act(user_id, "Account approved. The staff member can now sign in.", services.approve)


@bp.post("/<int:user_id>/reject")
@admin_only
def reject(user_id):
    return _act(user_id, "Account rejected.", services.reject, request.form.get("reason"))


@bp.post("/<int:user_id>/suspend")
@admin_only
def suspend(user_id):
    return _act(user_id, "Account suspended. Their session ends on their next request.",
                services.suspend, request.form.get("reason"))


@bp.post("/<int:user_id>/reactivate")
@admin_only
def reactivate(user_id):
    return _act(user_id, "Account reactivated.", services.reactivate)


@bp.post("/<int:user_id>/deactivate")
@admin_only
def deactivate(user_id):
    return _act(user_id, "Account deactivated. Order and payment history is kept.",
                services.deactivate, request.form.get("reason"))


@bp.post("/<int:user_id>/enroll-link")
@admin_only
def enroll_link(user_id):
    user = _staff_or_404(user_id)
    try:
        url, expires = services.issue_enrollment_link(user_id, current_user)
    except ActionError as exc:
        flash(str(exc), "error")
        return redirect(url_for("staff_admin.detail", user_id=user_id))
    return _no_store(make_response(render_template(
        "staff_admin/link.html", staff=user, enroll_url=url, expires=expires, replacement=True)))
