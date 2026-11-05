"""Account-management audit trail. Reuses the existing `auth_events` table (the same log the
sign-in code writes to) so there is a single activity log. Never pass secrets, tokens, passwords
or identity-document data in `detail`."""
from flask import has_request_context, request

from app.extensions import db
from app.models import AuthEvent


def record_event(event, *, success=True, actor=None, target=None, email=None, detail=None, commit=False):
    """Add an audit row. `actor` performed the action (None = the system/CLI); `target` is the
    account affected. The caller normally commits together with the change being audited."""
    ip = ua = None
    if has_request_context():
        ip = (request.remote_addr or "")[:45] or None
        ua = (request.user_agent.string or "")[:255] or None
    db.session.add(AuthEvent(
        user_id=getattr(actor, "id", None),
        target_user_id=getattr(target, "id", None),
        email=email or getattr(target, "email", None) or getattr(actor, "email", None),
        event=event[:40], success=success, ip=ip, user_agent=ua,
        detail=(detail or "")[:500] or None,
    ))
    if commit:
        db.session.commit()
