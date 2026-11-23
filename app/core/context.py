"""Values that are made available to every template."""

from datetime import datetime

from app.core import bp


@bp.app_context_processor
def inject_globals():
    """Add `now_year` to every template (used for the footer copyright year)."""
    return {"now_year": datetime.now().year}
