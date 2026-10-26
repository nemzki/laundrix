from datetime import timedelta

import click

from app.extensions import db
from app.identity import services, statuses as st
from app.models import IdentityVerification, User
from app.models.staff_credential import utcnow


def register_identity_commands(app):
    @app.cli.command("idv-status")
    @click.argument("email")
    def idv_status(email):
        """Show a user's verification attempts (status only; there is nothing sensitive to show)."""
        user = db.session.execute(db.select(User).filter_by(email=email.strip().lower())).scalar_one_or_none()
        if not user:
            click.secho("No such user.", fg="red")
            raise SystemExit(1)
        rows = services.history_for(user, limit=20, purpose=None)  # all purposes
        if not rows:
            click.echo("not_started (no attempts)")
        for r in rows:
            click.echo(f"{r.created_at:%Y-%m-%d %H:%M} {r.public_id[:8]} {r.purpose:<14} {r.environment:<8} "
                       f"{r.status:<16} codes={r.reason_codes or '-'} err={r.error_code or '-'}")

    @app.cli.command("idv-reconcile")
    @click.option("--older-than-minutes", default=10, show_default=True)
    def idv_reconcile(older_than_minutes):
        """Poll the provider for attempts whose webhook may have been missed."""
        cutoff = utcnow() - timedelta(minutes=older_than_minutes)
        rows = db.session.execute(
            db.select(IdentityVerification).where(
                db.or_(
                    db.and_(IdentityVerification.purpose == services.PURPOSE_KYC,
                            IdentityVerification.status.in_(services.OPEN_STATUSES)),
                    db.and_(IdentityVerification.purpose == services.PURPOSE_BIOMETRIC,
                            IdentityVerification.status.in_(services.BIOMETRIC_OPEN_STATUSES)),
                ),
                IdentityVerification.provider_session_id.is_not(None),
                IdentityVerification.updated_at < cutoff,
            )
        ).scalars().all()
        counts = {}
        for v in rows:
            outcome = services.reconcile(v, force=True).outcome
            counts[outcome] = counts.get(outcome, 0) + 1
        click.echo(f"checked {len(rows)}: {counts or 'nothing to do'}")

    @app.cli.command("idv-purge")
    @click.option("--days", default=None, type=int, help="Defaults to IDV_RETENTION_DAYS")
    @click.option("--dry-run", is_flag=True)
    def idv_purge(days, dry_run):
        """Delete verification records past the retention window."""
        days = days or app.config["IDV_RETENTION_DAYS"]
        result = services.purge_old_records(days, dry_run=dry_run)
        label = "would delete" if dry_run else "deleted"
        click.echo(f"{label} {result['matched']} record(s) older than {days} days")
