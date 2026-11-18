"""Admin analytics and reporting pages."""
import click
from flask import Blueprint, current_app

bp = Blueprint(
    "analytics",
    __name__,
    template_folder="templates",
    static_folder="static",
)


@bp.cli.command("train-demo")
@click.option("--samples", default=800, type=click.IntRange(200, 5000), show_default=True)
def train_demo(samples):
    """Train a clearly labelled development model using synthetic in-memory data."""
    from app.analytics.ml.demo_training import train_demo_models

    result = train_demo_models(current_app.instance_path, samples=samples)
    click.echo("Development-only synthetic model training completed.")
    click.echo(f"Selected model: {result['selected_model']}")
    click.echo(f"Samples: {result['samples']} (synthetic; never inserted into MySQL)")
    click.echo(f"Metrics: {result['metrics'][result['selected_model']]}")
    click.echo("WARNING: This model must not be used for real customer/order decisions.")


@bp.cli.command("train-production")
def train_production():
    """Train only when genuine Laundrix history meets readiness and split checks."""
    from app.analytics.ml.production_training import train_production_model

    try:
        result = train_production_model(current_app.instance_path)
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo("Production model trained from genuine Laundrix history.")
    click.echo(f"Selected model: {result['selected_model']}")
    click.echo(f"Eligible orders: {result['eligible_samples']}")
    click.echo(f"Held-out chronological test metrics: {result['held_out_test_metrics']}")
    click.echo("Review the test metrics before using predictions operationally.")


@bp.cli.command("import-history")
@click.option(
    "--file",
    "file_path",
    required=True,
    type=click.Path(exists=True, dir_okay=False, path_type=str),
    help="Path to the historical CSV file.",
)
@click.option(
    "--source",
    "import_source",
    default=None,
    help="Stable source name used to identify imported records.",
)
@click.option(
    "--execute",
    is_flag=True,
    help="Write validated records to the database. Without this flag, runs a dry-run.",
)
def import_history(file_path, import_source, execute):
    """Validate or import historical transaction records."""
    from sqlalchemy.engine import make_url

    from app.analytics.importers.service import (
        import_historical_transactions,
    )

    database_uri = current_app.config.get("SQLALCHEMY_DATABASE_URI")
    database_name = make_url(database_uri).database

    click.echo(f"Database target: {database_name or 'unknown'}")
    click.echo(f"Mode: {'EXECUTE' if execute else 'DRY-RUN'}")

    try:
        result = import_historical_transactions(
            file_path=file_path,
            import_source=import_source,
            execute=execute,
        )
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc

    click.echo(f"Source: {result['import_source']}")
    click.echo(f"CSV rows: {result['total_rows']}")
    click.echo(f"New records: {result['inserted']}")
    click.echo(f"Identical records skipped: {result['skipped']}")

    if execute:
        click.echo("Import completed.")
    else:
        click.echo("Dry-run completed. No database records were written.")


from app.analytics import routes  # noqa: E402,F401
