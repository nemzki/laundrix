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


from app.analytics import routes  # noqa: E402,F401
