from flask import render_template

from app.core import bp
from app.extensions import db

MESSAGES = {
    403: ("Access denied", "You don't have permission to view this page."),
    404: ("Page not found", "The page you're looking for doesn't exist."),
    429: ("Slow down", "Too many requests. Please try again in a moment."),
    500: ("Something went wrong", "An unexpected error occurred. Please try again."),
}


def _render(code):
    title, message = MESSAGES[code]
    return render_template("core/error.html", code=code, title=title, message=message), code


@bp.app_errorhandler(403)
def forbidden(_):
    return _render(403)


@bp.app_errorhandler(404)
def not_found(_):
    return _render(404)


@bp.app_errorhandler(429)
def too_many(_):
    return _render(429)


@bp.app_errorhandler(500)
def server_error(_):
    db.session.rollback()
    return _render(500)
