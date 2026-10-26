"""Authorization rules for Google sign-ins (kept separate from the HTTP layer)."""
from datetime import datetime, timezone

from flask import current_app

from app.extensions import db
from app.models import Role, User

DENIED = "This Google account is not authorized for Laundrix. Please contact your administrator."


def authorize_google_user(userinfo: dict):
    """Return (user, error). Only pre-registered, active users may sign in."""
    sub = userinfo.get("sub")
    email = (userinfo.get("email") or "").strip().lower()

    if not sub or not email:
        return None, DENIED
    if not userinfo.get("email_verified"):
        return None, "Your Google email address is not verified."

    domain = current_app.config.get("GOOGLE_ALLOWED_DOMAIN")
    if domain and not email.endswith("@" + domain):
        return None, DENIED

    user = db.session.execute(db.select(User).filter_by(google_sub=sub)).scalar_one_or_none()
    if user is None:
        user = db.session.execute(db.select(User).filter_by(email=email)).scalar_one_or_none()
        # An email already linked to a *different* Google account must not be taken over.
        if user is not None and user.google_sub and user.google_sub != sub:
            return None, DENIED

    if user is None or not user.is_active:
        return None, DENIED

    if user.role == Role.STAFF and not current_app.config.get("STAFF_GOOGLE_LOGIN_ALLOWED"):
        return None, "Staff accounts sign in through the Staff Portal."

    user.google_sub = sub
    user.email = email
    user.full_name = userinfo.get("name") or user.full_name
    user.picture_url = userinfo.get("picture") or user.picture_url
    user.last_login_at = datetime.now(timezone.utc).replace(tzinfo=None)
    db.session.commit()
    return user, None
