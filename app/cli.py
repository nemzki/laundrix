import click
from sqlalchemy import text

from app.audit import services as audit
from app.extensions import db
from app.models import Role, User


def register_commands(app):
    from app.staff_auth.cli import register_staff_commands

    register_staff_commands(app)

    from app.identity.cli import register_identity_commands

    register_identity_commands(app)

    from app.catalog.cli import register_catalog_commands

    register_catalog_commands(app)

    from app.payments.cli import register_payment_commands

    register_payment_commands(app)

    from app.auth.cli import register_auth_commands

    register_auth_commands(app)

    @app.cli.command("check-db")
    def check_db():
        """Test the MySQL connection."""
        try:
            version = db.session.execute(text("SELECT VERSION()")).scalar()
            name = db.session.execute(text("SELECT DATABASE()")).scalar()
            click.secho(f"Connected to '{name}' (MySQL {version})", fg="green")
        except Exception as exc:  # noqa: BLE001
            click.secho(f"Database connection failed: {exc}", fg="red")
            raise SystemExit(1)

    @app.cli.command("create-user")
    @click.argument("email")
    @click.option("--role", type=click.Choice([Role.ADMIN, Role.STAFF]), default=Role.STAFF)
    @click.option("--name", default=None, help="Optional display name")
    def create_user(email, role, name):
        """Pre-authorize a Google account, e.g.  flask create-user me@gmail.com --role admin"""
        email = email.strip().lower()
        if db.session.execute(db.select(User).filter_by(email=email)).scalar_one_or_none():
            click.secho("A user with that email already exists.", fg="yellow")
            return
        user = User(email=email, role=role, full_name=name)
        db.session.add(user)
        db.session.flush()
        audit.record(audit.AuditAction.CREATE, audit.AuditModule.ACCOUNTS,
                     f"Created {role} account {email} from the command line", actor=None,
                     resource_id=user.id, resource_label=f"Account: {name or email}",
                     new={"role": role})
        db.session.commit()
        click.secho(f"Created {role}: {email}", fg="green")
