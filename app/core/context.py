from datetime import datetime

from app.core import bp


@bp.app_context_processor
def inject_globals():
    return {"now_year": datetime.now().year}
