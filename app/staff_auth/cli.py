import click

from app.extensions import db
from app.models import Role, User
from app.staff_auth import services
from getpass import getpass
from werkzeug.security import generate_password_hash

def _find_staff(email):
    user = db.session.execute(
        db.select(User).filter_by(email=email.strip().lower())
    ).scalar_one_or_none()
    if not user or user.role != Role.STAFF:
        click.secho("No staff member with that email.", fg="red")
        raise SystemExit(1)
    return user


def _print_link(app, token):
    hours = app.config["STAFF_ENROLL_TOKEN_HOURS"]
    click.echo(f"  Enrollment link ({hours}h, single-use): {app.config['APP_BASE_URL']}/staff/enroll/{token}")


def register_staff_commands(app):
    @app.cli.command("create-staff")
    @click.argument("email")
    @click.option("--name", default=None, help="Full name")
    @click.option("--staff-id", default=None, help="Custom Staff ID (default: auto-generated)")
    def create_staff(email, name, staff_id):
        """Create a staff account: prints a Staff ID (once) and a one-time enrollment link."""
        try:
            user, sid, token = services.create_staff(email, name, staff_id)
        except ValueError as exc:
            click.secho(str(exc), fg="red")
            raise SystemExit(1)
        click.secho(f"\nStaff: {user.email}", bold=True)
        click.echo(f"  Staff ID (shown ONCE):        {sid}")
        _print_link(app, token)
        click.secho("\nSend the Staff ID and the link through DIFFERENT channels.", fg="yellow")

    @app.cli.command("new-enroll-link")
    @click.argument("email")
    def new_enroll_link(email):
        """New one-time link so the person can (re)verify their identity with Didit.

        Keeps their existing Staff ID. Use it to move staff over from the old AWS face system,
        or when a verification has expired."""
        user = _find_staff(email)
        try:
            token = services.new_enroll_link(user)
        except ValueError as exc:
            click.secho(str(exc), fg="red")
            raise SystemExit(1)
        click.secho(f"\nStaff: {user.email}", bold=True)
        _print_link(app, token)

    @app.cli.command("reset-staff")
    @click.argument("email")
    @click.option("--staff-id", default=None)
    def reset_staff(email, staff_id):
        """Lost Staff ID: issue a NEW one and clear any lockout (identity verification is kept)."""
        user = _find_staff(email)
        try:
            sid = services.reset_staff_id(user, staff_id)
        except ValueError as exc:
            click.secho(str(exc), fg="red")
            raise SystemExit(1)
        click.secho(f"\nStaff: {user.email}", bold=True)
        click.echo(f"  New Staff ID (shown ONCE):    {sid}")

    @app.cli.command("staff-status")
    @click.argument("email")
    def staff_status(email):
        """Show whether a staff member is verified, locked, or has a live enrollment link."""
        user = _find_staff(email)
        cred = user.staff_credential
        click.echo(f"{user.email}  active={user.is_active}  verified={services.is_enrolled(user)}  "
                   f"locked={bool(cred and cred.is_locked)}  "
                   f"link_pending={bool(cred and cred.enroll_token_hash)}  "
                   f"last_signin={cred.last_verified_at if cred else None}")

    @app.cli.command("set-staff-password")
    @click.argument("email")
    def set_staff_password(email):
        """Set a staff password without changing Staff ID or Didit records."""
        user = _find_staff(email)

        if not user.is_active:
            click.secho("Cannot set a password for an inactive staff account.", fg="red")
            raise SystemExit(1)

        if not services.is_enrolled(user):
            click.secho(
                "Cannot set a password: staff identity verification is incomplete.",
                fg="red",
            )
            raise SystemExit(1)

        cred = user.staff_credential
        if cred is None:
            click.secho("Staff credentials were not found.", fg="red")
            raise SystemExit(1)

        password = getpass("New password (minimum 12 characters): ")
        confirm = getpass("Confirm password: ")

        if len(password) < 12 or len(password) > 256:
            click.secho("Password must be between 12 and 256 characters.", fg="red")
            raise SystemExit(1)

        if password != confirm:
            click.secho("Passwords do not match.", fg="red")
            raise SystemExit(1)

        cred.password_hash = generate_password_hash(password)
        cred.failed_attempts = 0
        cred.locked_until = None
        db.session.commit()

        click.secho(f"Password set successfully for {user.email}.", fg="green")

    @app.cli.command("deactivate-staff")
    @click.argument("email")
    def deactivate_staff(email):
        """Offboarding: disable sign-in and kill any enrollment link."""
        user = _find_staff(email)
        services.deactivate_staff(user)
        click.secho(f"{user.email} deactivated.", fg="green")
        click.secho(
            f"REMINDER: Didit still holds this person's verification data (reference: laundrix:{user.id}). "
            "Delete it in the Didit console as your retention policy requires.", fg="yellow")
