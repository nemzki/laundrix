"""Command-line commands for administrator accounts (bootstrap-admin, rotate-admin-password)."""

import click

from app.auth import bootstrap
from app.extensions import db
from app.models import Role, User


def register_auth_commands(app):
    """Attach the administrator-account `flask ...` commands to the app."""
    @app.cli.command("bootstrap-admin")
    @click.option("--allow-additional", is_flag=True,
                  help="Create the initial administrator even if another administrator already exists.")
    def bootstrap_admin(allow_additional):
        """Create the initial administrator from INITIAL_ADMIN_USERNAME / INITIAL_ADMIN_PASSWORD.

        Safe to run repeatedly: an existing account is never recreated or changed."""
        cfg = app.config
        result = bootstrap.create_initial_admin(
            cfg.get("INITIAL_ADMIN_USERNAME"), cfg.get("INITIAL_ADMIN_PASSWORD"),
            cfg.get("INITIAL_ADMIN_EMAIL"), allow_additional=allow_additional,
        )
        color = {"created": "green", "exists": "yellow", "skipped_other_admin": "yellow"}.get(result.status, "red")
        click.secho(result.message, fg=color)
        if result.status == "created":
            click.echo("Sign in at /auth/admin. Remove INITIAL_ADMIN_PASSWORD from .env now that it has been used.")
        if result.status == "invalid":
            raise SystemExit(1)

    @app.cli.command("rotate-admin-password")
    @click.argument("identifier", required=False)
    def rotate_admin_password(identifier):
        """Set or change an administrator's password (prompted; never read from the environment).

        IDENTIFIER is the administrator's email or username. Use the email for an account that was
        created for Google sign-in: it has no password yet, and this gives it one."""
        ident = (identifier or app.config.get("INITIAL_ADMIN_USERNAME") or "").strip().lower()
        column = User.email if "@" in ident else User.username
        user = db.session.execute(db.select(User).where(column == ident)).scalar_one_or_none() if ident else None
        if user is None or user.role != Role.ADMIN:
            click.secho("No administrator with that email or username.", fg="red")
            raise SystemExit(1)
        password = click.prompt("New password", hide_input=True, confirmation_prompt=True)
        try:
            bootstrap.rotate_password(user, password)
        except ValueError as exc:
            click.secho(str(exc), fg="red")
            raise SystemExit(1)
        click.secho(f"Password set for '{user.username or user.email}'.", fg="green")
        click.echo("Sign in at /auth/admin with this email or username and the new password.")
