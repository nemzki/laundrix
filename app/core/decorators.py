"""Reusable decorators for protecting views."""

from functools import wraps

from flask import abort, current_app
from flask_login import current_user


def role_required(*roles):
    """Restrict a view to users whose role is in `roles` (e.g. Role.ADMIN)."""
    def decorator(view):
        """Wrap a view function so the role check runs before it."""
        @wraps(view)
        def wrapped(*args, **kwargs):
            """Run the checks, then the real view.

            Not signed in -> send to the login page. Signed in with the wrong role -> 403 error.
            Otherwise call the original view."""
            if not current_user.is_authenticated:
                return current_app.login_manager.unauthorized()
            if current_user.role not in roles:
                abort(403)
            return view(*args, **kwargs)
        return wrapped
    return decorator
