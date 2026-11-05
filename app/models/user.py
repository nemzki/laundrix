from datetime import datetime, timezone

from flask_login import UserMixin

from app.extensions import db


class Role:
    ADMIN = "admin"
    STAFF = "staff"
    ALL = (ADMIN, STAFF)


class AccountStatus:
    """Lifecycle of an account. `active` is the only state allowed to use operational features.

    Existing accounts default to `active`, so nothing that worked before changes behaviour."""
    PENDING_VERIFICATION = "pending_verification"   # registered with Google, Didit check not passed yet
    PENDING_APPROVAL = "pending_approval"           # identity verified, waiting for an administrator
    ACTIVE = "active"
    REJECTED = "rejected"
    SUSPENDED = "suspended"
    DEACTIVATED = "deactivated"
    ALL = (PENDING_VERIFICATION, PENDING_APPROVAL, ACTIVE, REJECTED, SUSPENDED, DEACTIVATED)
    PENDING = (PENDING_VERIFICATION, PENDING_APPROVAL)
    BLOCKED = (REJECTED, SUSPENDED, DEACTIVATED)    # may not hold a session at all
    LABELS = {
        PENDING_VERIFICATION: "Pending verification", PENDING_APPROVAL: "Pending approval",
        ACTIVE: "Active", REJECTED: "Rejected", SUSPENDED: "Suspended", DEACTIVATED: "Deactivated",
    }
    TONES = {
        PENDING_VERIFICATION: "warn", PENDING_APPROVAL: "progress", ACTIVE: "success",
        REJECTED: "neutral", SUSPENDED: "warn", DEACTIVATED: "neutral",
    }


def _utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


class User(UserMixin, db.Model):

    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    google_sub = db.Column(db.String(64), unique=True, nullable=True)  # Google's stable user id
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)
    full_name = db.Column(db.String(150))
    picture_url = db.Column(db.String(500))
    role = db.Column(
        db.Enum(*Role.ALL, name="user_role"), nullable=False, default=Role.STAFF
    )
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, nullable=False, default=_utcnow)
    last_login_at = db.Column(db.DateTime)

    # --- account lifecycle (staff management) -------------------------------------------
    account_status = db.Column(
        db.String(24), nullable=False, default=AccountStatus.ACTIVE,
        server_default=AccountStatus.ACTIVE, index=True,
    )
    status_reason = db.Column(db.String(255))                       # why it was rejected/suspended/deactivated
    status_changed_at = db.Column(db.DateTime)
    status_changed_by_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"))
    approved_at = db.Column(db.DateTime)
    approved_by_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"))

    # --- administrator username/password sign-in (never used by staff) ---------------------
    username = db.Column(db.String(40), unique=True)
    password_hash = db.Column(db.String(255))
    failed_login_attempts = db.Column(db.Integer, nullable=False, default=0, server_default="0")
    locked_until = db.Column(db.DateTime)

    __table_args__ = (
        db.CheckConstraint(
            "account_status IN ('pending_verification', 'pending_approval', 'active', "
            "'rejected', 'suspended', 'deactivated')",
            name="ck_users_account_status",
        ),
    )

    @property
    def is_admin(self) -> bool:
        return self.role == Role.ADMIN

    @property
    def is_operational(self) -> bool:
        """May use operational features: enabled AND approved."""
        return bool(self.is_active and self.account_status == AccountStatus.ACTIVE)

    @property
    def is_locked(self) -> bool:
        return self.locked_until is not None and self.locked_until > _utcnow()

    def __repr__(self):
        return f"<User {self.email} ({self.role})>"
