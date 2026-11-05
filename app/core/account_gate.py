"""One central, default-deny check of the signed-in account's state, run on EVERY request.

It sits in front of all blueprints, so direct URLs and JSON/API calls get exactly the same
protection as the pages:

* rejected / suspended / deactivated / disabled accounts lose their session immediately
  (this is the session revocation: the next request after the status change is signed out);
* accounts still waiting for verification or approval keep a restricted session that can only
  reach identity verification, their status page and sign-out;
* only `active` accounts reach operational features.

Existing active users are unaffected."""
from flask import abort, flash, redirect, request, session, url_for
from flask_login import current_user, logout_user

from app.models import AccountStatus, User

# Endpoints a restricted (pending) account may use.
RESTRICTED_ALLOWED_ENDPOINTS = {"auth.logout", "auth.login", "landing.index"}
RESTRICTED_ALLOWED_PREFIXES = ("identity.", "staff_register.")

BLOCKED_MESSAGES = {
    AccountStatus.SUSPENDED: "Your account is suspended. Please contact your administrator.",
    AccountStatus.DEACTIVATED: "This account has been deactivated.",
    AccountStatus.REJECTED: "Your registration was not approved.",
}
DISABLED_MESSAGE = "This account is not active. Please contact your administrator."


def _is_static(endpoint: str) -> bool:
    return endpoint == "static" or endpoint.endswith(".static")


def enforce_account_status():
    endpoint = request.endpoint
    if endpoint is None:
        return None                                   # unknown URL: let Flask answer 404/405

    # NOTE: do NOT use current_user.is_authenticated here. Flask-Login's UserMixin defines it as
    # `is_active`, so a suspended/deactivated/disabled user reports "not authenticated" and would
    # slip past this check with their session cookie intact. Look at the loaded user object itself.
    user = current_user._get_current_object()
    if not isinstance(user, User):
        return None                                   # genuine anonymous visitor

    status = getattr(user, "account_status", None) or AccountStatus.ACTIVE

    if not user.is_active or status in AccountStatus.BLOCKED:
        message = BLOCKED_MESSAGES.get(status, DISABLED_MESSAGE)
        logout_user()
        session.clear()                               # revoke the session cookie data
        if not _is_static(endpoint):
            flash(message, "error")
        # Carry on as an anonymous visitor: protected views then send them to the sign-in page
        # exactly as for any signed-out user, while public pages (landing, tracking) still work.
        return None

    if status in AccountStatus.PENDING:
        if (endpoint in RESTRICTED_ALLOWED_ENDPOINTS or _is_static(endpoint)
                or endpoint.startswith(RESTRICTED_ALLOWED_PREFIXES)):
            return None
        if request.method in ("GET", "HEAD"):
            return redirect(url_for("identity.index"))
        abort(403)

    return None
