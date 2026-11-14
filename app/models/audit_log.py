from sqlalchemy import event

from app.extensions import db
from app.models.staff_credential import utcnow


class AuditLogImmutableError(RuntimeError):
    """Raised when application code tries to change or delete an audit record."""


class AuditLog(db.Model):
    """Append-only trail of important business and security actions (no secrets, no credentials).

    The actor's name and role are *snapshots*: they stay correct even if the account is later
    renamed, demoted or removed (`actor_id` becomes NULL if the user row is ever deleted).

    module        = which part of Laundrix the action belongs to (see AuditModule)
    resource_id   = identifier of the affected record (order reference, customer id, ...)
    resource_label= short human label of that record, e.g. "Order LX-261114-AB12C"
    old/new_values= only the fields that changed, already sanitised (see app/audit/services.py)
    """
    __tablename__ = "audit_logs"
    __table_args__ = (
        db.Index("ix_audit_logs_module_created", "module", "created_at"),
        db.Index("ix_audit_logs_action_created", "action", "created_at"),
        db.Index("ix_audit_logs_actor_created", "actor_id", "created_at"),
    )

    id = db.Column(db.Integer, primary_key=True)
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow, index=True)
    actor_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"))
    actor_name = db.Column(db.String(150), nullable=False)
    actor_role = db.Column(db.String(20))
    action = db.Column(db.String(40), nullable=False)
    module = db.Column(db.String(40), nullable=False)
    resource_id = db.Column(db.String(64))
    resource_label = db.Column(db.String(150))
    description = db.Column(db.String(500), nullable=False)
    old_values = db.Column(db.JSON)
    new_values = db.Column(db.JSON)
    success = db.Column(db.Boolean, nullable=False, default=True)
    ip_address = db.Column(db.String(45))


@event.listens_for(AuditLog, "before_update")
def _block_update(mapper, connection, target):
    raise AuditLogImmutableError("Audit records cannot be modified.")


@event.listens_for(AuditLog, "before_delete")
def _block_delete(mapper, connection, target):
    raise AuditLogImmutableError("Audit records cannot be deleted.")
