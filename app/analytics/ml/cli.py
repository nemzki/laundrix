"""Read-only ML commands.  Training commands arrive with the model lifecycle (D7: CLI only)."""
import json

import click


def register_ml_commands(app):
    register_training_commands(app)

    @app.cli.command("analytics-readiness")
    @click.option("--json", "as_json", is_flag=True, help="Print the full report as JSON.")
    def analytics_readiness(as_json):
        """Show whether the historical data can support forecasting. Read-only; trains nothing."""
        from app.analytics.ml.readiness import assess_now

        report = assess_now()
        if as_json:
            click.echo(json.dumps(report.as_dict(), indent=2, default=str))
            return

        ok = report.status == "ready_for_training"
        click.secho(f"Status: {report.as_dict()['model_status_label']}", fg="green" if ok else "yellow", bold=True)
        click.echo(report.message)
        click.echo(f"History runs up to {report.as_of:%Y-%m-%d} (today is excluded: it is incomplete). Philippine time.\n")
        click.echo(f"{'Target':<30}{'Step':<8}{'Available':<14}{'Needed':<10}Status")
        for t in report.targets:
            click.echo(f"{t.label:<30}{t.granularity:<8}{t.observations:<14}{t.required:<10}"
                       + ("READY FOR TRAINING" if t.ready else "INSUFFICIENT DATA"))
        s = report.services
        click.echo(f"{'Service demand (weekly)':<30}{'week':<8}{s.ready_entities}/{s.total_entities} services ready")
        click.echo("\nDetails:")
        for t in report.targets:
            click.echo(f"  - {t.message}")
        click.echo(f"  - {s.message}")
        q = report.quality
        click.echo(f"\nOrders: {q.get('total_orders', 0)} total, {q.get('eligible_orders', 0)} eligible "
                   f"(received and valid), {q.get('awaiting_receipt', 0)} awaiting receipt.")
        for i in report.issues:
            click.echo(f"  [{i.severity}] {i.message}")


_TARGETS = ("orders", "gross_order_value", "net_collections", "service_demand")


def register_training_commands(app):
    @app.cli.command("analytics-train")
    @click.option("--target", "targets", multiple=True, type=click.Choice(_TARGETS), help="Limit to one or more targets.")
    @click.option("--dry-run", is_flag=True, help="Evaluate and report only; write nothing.")
    @click.option("--strict", is_flag=True, help="Exit 2 if anything could not be trained (for automation).")
    def analytics_train(targets, dry_run, strict):
        """Train, evaluate and (only if it passes) activate forecasting models.

        Never runs on a web request. Insufficient data is reported, not trained on. A model that fails
        the documented criteria is recorded as EVALUATION FAILED and the previous model stays active.
        """
        try:
            from app.analytics.ml.training import Outcome, train
            report = train(targets=list(targets) or None, dry_run=dry_run)
        except ImportError as exc:
            click.secho(f"A required package is missing ({exc.name}). Run: pip install numpy scikit-learn", fg="red", err=True)
            raise SystemExit(1)

        colours = {Outcome.PROMOTED: "green", Outcome.KEPT_PREVIOUS: "cyan", Outcome.EVALUATION_FAILED: "yellow",
                   Outcome.INSUFFICIENT: "yellow", Outcome.IN_PROGRESS: "yellow", Outcome.ERROR: "red"}
        names = {Outcome.PROMOTED: "ACTIVATED" if not dry_run else "WOULD ACTIVATE", Outcome.KEPT_PREVIOUS: "KEPT PREVIOUS",
                 Outcome.EVALUATION_FAILED: "EVALUATION FAILED", Outcome.INSUFFICIENT: "INSUFFICIENT DATA",
                 Outcome.IN_PROGRESS: "ALREADY TRAINING", Outcome.ERROR: "ERROR"}
        click.secho("Dry run: nothing is written.\n" if dry_run else "", fg="cyan", nl=bool(dry_run))
        for o in report.outcomes:
            click.secho(f"[{names[o.outcome]}] {o.label}", fg=colours[o.outcome], bold=True)
            if o.algorithm:
                bits = [f"{o.algorithm} ({'machine learning' if o.kind == 'ml' else 'statistical baseline'})"]
                if o.test_mae is not None:
                    bits.append(f"test MAE {o.test_mae}")
                bits.append("WAPE " + ("undefined" if o.test_wape is None else f"{o.test_wape:.1%}"))
                if o.skill is not None:
                    bits.append(f"skill vs historical average {o.skill:.1%}")
                click.echo("    " + "; ".join(bits))
            if o.message:
                click.echo(f"    {o.message}")
        total = len(report.outcomes)
        click.echo(f"\n{total} target(s) examined: "
                   + ", ".join(f"{report.count(k)} {names[k].lower()}" for k in colours if report.count(k)) + ".")
        click.echo("Forecasts are estimates. Passing evaluation does not guarantee future accuracy.")
        raise SystemExit(report.exit_code(strict))

    @app.cli.command("analytics-status")
    def analytics_status():
        """Show the status of every forecasting model. Read-only."""
        from app.analytics.ml.serving import forecast_overview

        data = forecast_overview()
        click.echo(f"{'Target':<30}{'Step':<7}{'Status':<22}{'Model'}")
        for t in data["targets"]:
            m = t["model"]
            model = f"v{m['version']} {m['algorithm']} ({m['kind_label']})" if m else "-"
            click.echo(f"{t['label']:<30}{t['granularity']:<7}{t['status_label']:<22}{model}")
            if t["message"] and not t["usable"]:
                click.echo(f"    {t['message']}")
        s = data["services"]
        ranked = len(s["rankings"]["primary"]) + len(s["rankings"]["addons"])
        click.echo(f"\nService demand: {ranked} with a validated model, {len(s['unavailable'])} waiting for data or training.")
        click.echo(data["disclaimer"])
