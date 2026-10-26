from datetime import datetime, timezone

from flask_login import UserMixin

from app.extensions import db


class Role:
    ADMIN = "admin"
    STAFF = "staff"
    ALL = (ADMIN, STAFF)


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

    @property
    def is_admin(self) -> bool:
        return self.role == Role.ADMIN

    def __repr__(self):
        return f"<User {self.email} ({self.role})>"
