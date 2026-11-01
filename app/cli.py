import click
from sqlalchemy import text

from app.extensions import db
from app.models import Role, User


def register_commands(app):
    from app.staff_auth.cli import register_staff_commands

    register_staff_commands(app)

    from app.identity.cli import register_identity_commands

    register_identity_commands(app)

    from app.catalog.cli import register_catalog_commands

    register_catalog_commands(app)

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
        db.session.add(User(email=email, role=role, full_name=name))
        db.session.commit()
        click.secho(f"Created {role}: {email}", fg="green")
