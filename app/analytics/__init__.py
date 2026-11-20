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
    """Train the unclaimed-order model from Laundrix's own confirmed orders (if there is enough data)."""
    from app.analytics.ml.training import NotReady, NotReliable, train_model

    try:
        run = train_model()
    except (NotReady, NotReliable) as exc:
        raise click.ClickException(str(exc)) from exc

    metrics = run.metrics
    click.echo(f"Model version {run.version} trained and set as the active model.")
    click.echo(f"Confirmed orders used: {run.n_orders} (disposed: {run.n_disposed}), "
               f"ready dates {run.data_start} to {run.data_end}")
    click.echo(
        f"Test on the newest {metrics['test_orders']} orders ({metrics['test_disposed']} disposed): "
        f"accuracy {metrics['accuracy']}, precision {metrics['precision']}, "
        f"recall {metrics['recall']}, ROC-AUC {metrics['roc_auc']}."
    )


@bp.cli.command("purge-simulated")
@click.option("--execute", is_flag=True, help="Delete the rows. Without this flag only counts them.")
def purge_simulated(execute):
    """Remove imported history rows whose outcomes are marked 'simulated' (placeholder data)."""
    from app.extensions import db
    from app.models import HistoricalTransaction

    rows = db.session.scalar(
        db.select(db.func.count(HistoricalTransaction.id)).where(HistoricalTransaction.status_source == "simulated")
    )
    click.echo(f"Imported rows with simulated outcomes: {rows}")
    if not execute:
        click.echo("Dry-run. Nothing was deleted. Add --execute to delete them.")
        return
    db.session.execute(db.delete(HistoricalTransaction).where(HistoricalTransaction.status_source == "simulated"))
    db.session.commit()
    click.echo("Deleted.")


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
