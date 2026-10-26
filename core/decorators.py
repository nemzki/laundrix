from functools import wraps

from flask import abort, current_app
from flask_login import current_user


def role_required(*roles):
    """Restrict a view to users whose role is in `roles` (e.g. Role.ADMIN)."""
    def decorator(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            if not current_user.is_authenticated:
                return current_app.login_manager.unauthorized()
            if current_user.role not in roles:
                abort(403)
            return view(*args, **kwargs)
        return wrapped
    return decorator
