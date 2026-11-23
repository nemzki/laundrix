"""Friendly error pages for 403, 404, 429 and 500 errors."""

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
    """Render the shared error page for an HTTP status code and return it with that code."""
    title, message = MESSAGES[code]
    return render_template("core/error.html", code=code, title=title, message=message), code


@bp.app_errorhandler(403)
def forbidden(_):
    """Handle 403: the user is not allowed to view the page."""
    return _render(403)


@bp.app_errorhandler(404)
def not_found(_):
    """Handle 404: the page does not exist."""
    return _render(404)


@bp.app_errorhandler(429)
def too_many(_):
    """Handle 429: too many requests (rate limit reached)."""
    return _render(429)


@bp.app_errorhandler(500)
def server_error(_):
    """Handle 500: an unexpected error.

    Rolls back the database session first so a half-finished transaction is not left open."""
    db.session.rollback()
    return _render(500)
