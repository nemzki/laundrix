import click

from app.payments.seed import seed_payments


def register_payment_commands(app):
    @app.cli.command("seed-payments")
    def seed_payments_command():
        """Create the default payment methods (Cash, GCash) and settings row if missing."""
        methods, settings = seed_payments()
        click.secho(f"Added {methods} payment methods, {settings} settings row (existing rows untouched).", fg="green")
