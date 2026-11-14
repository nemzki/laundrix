"""The Audit Logs card lives in Personal Settings (see app.core.routes._audit_context).

This blueprint keeps only the old URL, which forwards an admin to that card. It is READ ONLY and
ADMIN ONLY: there is no create/update/delete endpoint. Audit rows are written solely by
`app.audit.services.record()` from inside other business operations."""
from flask import abort, current_app, redirect, request, url_for
from flask_login import current_user

from app.audit import bp
from app.models import Role


@bp.before_request
def _admin_only():
    if not current_user.is_authenticated:
        return current_app.login_manager.unauthorized()
    if current_user.role != Role.ADMIN or not current_user.is_active:
        abort(403)
    return None


@bp.get("/")
def index():
    return redirect(url_for("core.personal_settings", _anchor="audit-logs", **request.args.to_dict()), code=302)
