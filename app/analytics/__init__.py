"""Admin analytics and reporting pages."""
import click
from flask import Blueprint, current_app

bp = Blueprint(
    "analytics",
    __name__,
    template_folder="templates",
    static_folder="static",
)


@bp.cli.command("train")
def train():
    """Train the unclaimed-order disposal-risk model from imported history."""
    from app.analytics.ml.training import train_model

    try:
        run = train_model()
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc

    metrics = run.metrics
    click.echo(f"Model version {run.version} trained and set as the active model.")
    click.echo(f"Orders used: {run.n_orders} (disposed: {run.n_disposed}), "
               f"ready dates {run.data_start} to {run.data_end}")
    click.echo(
        f"Test on the newest {metrics['test_orders']} orders "
        f"({metrics['test_disposed']} disposed): "
        f"accuracy {metrics['accuracy']}, precision {metrics['precision']}, "
        f"recall {metrics['recall']}, F1 {metrics['f1']}, ROC-AUC {metrics['roc_auc']} "
        f"(guessing 'claimed' every time scores {metrics['baseline_accuracy']})."
    )
    if run.labels_simulated:
        click.echo("WARNING: some outcome labels are simulated or unconfirmed. "
                   "Do not rely on these predictions for real decisions.")


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
    click.echo(f"Existing records with outcome updates: {result['updated']}")
    click.echo(f"Identical records skipped: {result['skipped']}")

    if execute:
        click.echo("Import completed.")
    else:
        click.echo("Dry-run completed. No database records were written.")


from app.analytics import routes  # noqa: E402,F401
