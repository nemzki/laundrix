import click

from app.catalog.seed import seed_catalog


def register_catalog_commands(app):
    @app.cli.command("seed-catalog")
    def seed_catalog_command():
        """Insert the confirmed WASH UP! catalog if missing (never overwrites existing rows)."""
        s, a, p = seed_catalog()
        click.secho(f"Added {s} services, {a} extras, {p} packages (existing rows untouched).", fg="green")
