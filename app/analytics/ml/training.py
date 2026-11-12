"""Controlled model training (never runs on a web request; invoked by ``flask analytics-train``).

For every forecasting target with enough history: evaluate -> decide -> record.
    * A model that fails the documented criteria is recorded as EVALUATION FAILED and activates nothing.
    * A model that passes but is worse than the active one on the same test window is saved, not activated.
    * Only a model that passes AND is not worse than the active one becomes the single active model,
      in one transaction.  The previous model is never deleted and stays active on any failure.
    * Insufficient data is reported, never trained on.  Nothing is invented.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime

from app.analytics.ml import evaluation as ev
from app.analytics.ml import model_registry as reg
from app.analytics.ml import readiness as rd
from app.analytics.ml.data_preparation import prepare_all
from app.analytics.ml.policy import DEFAULT_POLICY, Policy
from app.analytics.ml.schemas import Series, Target
from app.models import ModelRunStatus

log = logging.getLogger(__name__)


class Outcome:
    PROMOTED = "promoted"
    KEPT_PREVIOUS = "kept_previous"
    EVALUATION_FAILED = "evaluation_failed"
    INSUFFICIENT = "insufficient_data"
    IN_PROGRESS = "in_progress"
    ERROR = "error"


@dataclass(frozen=True)
class JobOutcome:
    key: reg.ModelKey
    label: str
    outcome: str
    message: str
    version: int | None = None
    algorithm: str | None = None
    kind: str | None = None
    test_mae: float | None = None
    test_wape: float | None = None
    skill: float | None = None


@dataclass
class TrainingReport:
    started_at: datetime
    dry_run: bool
    outcomes: list = field(default_factory=list)

    def count(self, outcome: str) -> int:
        return sum(1 for o in self.outcomes if o.outcome == outcome)

    def exit_code(self, strict: bool = False) -> int:
        """0 = finished (insufficient data and failed evaluation are normal, reported results);
        1 = at least one unexpected error; with ``strict`` also 2 when anything was not trained/promoted."""
        if self.count(Outcome.ERROR):
            return 1
        if strict and (self.count(Outcome.EVALUATION_FAILED) or self.count(Outcome.INSUFFICIENT) or self.count(Outcome.IN_PROGRESS)):
            return 2
        return 0


@dataclass(frozen=True)
class Job:
    key: reg.ModelKey
    label: str
    series: Series
    readiness: rd.TargetReadiness


def build_jobs(prepared, overview, targets=None) -> list[Job]:
    jobs: list[Job] = []
    wanted = set(targets) if targets else set(Target.ALL)
    for tr in overview.targets:
        if tr.target in wanted:
            jobs.append(Job(reg.ModelKey(tr.target, tr.granularity), f"{tr.label} ({tr.granularity}ly)"
                            if tr.granularity == "week" else f"{tr.label} (daily)", prepared.series(tr.target, tr.granularity), tr))
    if Target.SERVICE_DEMAND in wanted:
        by_key = {e.key: e for e in prepared.services}
        for tr in overview.services.entities:
            entity = by_key.get(tr.entity)
            if entity is not None:
                jobs.append(Job(reg.ModelKey(Target.SERVICE_DEMAND, "week", entity.key), f"Service demand: {entity.label}",
                                entity.orders_weekly, tr))
    return jobs


def _summary(evaluation: ev.Evaluation) -> dict:
    sel = evaluation.metrics.get("selected") or {}
    test = sel.get("test") or {}
    return {"algorithm": sel.get("algorithm"), "kind": sel.get("kind"), "test_mae": test.get("mae"),
            "test_wape": test.get("wape"), "skill": sel.get("skill_vs_reference")}


def _run_one(job: Job, policy: Policy, now_utc: datetime, dry_run: bool, trained_by: str) -> JobOutcome:
    champion, champion_note = None, ""
    previous = reg.active_run(job.key)
    if previous is not None:
        try:
            champion = reg.load_model(previous)
        except reg.ModelLoadError as exc:
            champion_note = f" (The current model was ignored: {exc})"

    series = job.series
    evaluation = ev.evaluate(series.values, series.start, series.granularity, policy, champion)
    s = _summary(evaluation)
    notes = " ".join(evaluation.reasons) + champion_note

    if dry_run:
        if not evaluation.passed:
            return JobOutcome(job.key, job.label, Outcome.EVALUATION_FAILED, notes or "Did not meet the criteria.", **s)
        out = Outcome.PROMOTED if evaluation.promote else Outcome.KEPT_PREVIOUS
        return JobOutcome(job.key, job.label, out, ("Dry run: would be activated. " if evaluation.promote
                                                    else "Dry run: the current model would stay active. ") + notes, **s)

    try:
        run = reg.begin_run(job.key, trained_by=trained_by, now_utc=now_utc, lock_minutes=policy.training_lock_minutes)
    except reg.TrainingInProgress as exc:
        return JobOutcome(job.key, job.label, Outcome.IN_PROGRESS, str(exc))

    run_id, version = run.id, run.version         # read now: after a failed DB operation the row would need a rollback first
    common = dict(now_utc=now_utc, data_start=series.start, data_end=series.end, n_observations=series.n, n_events=series.events)
    metrics = dict(evaluation.metrics)
    if evaluation.baseline is not None:
        metrics["baseline_algorithm"] = evaluation.baseline.algorithm
    try:
        if not evaluation.passed:
            reg.finish_run(run, status=ModelRunStatus.EVALUATION_FAILED, message=notes, metrics=metrics, **common)
            return JobOutcome(job.key, job.label, Outcome.EVALUATION_FAILED, notes, version, **s)
        reg.finish_run(run, status=ModelRunStatus.TRAINED, message=notes, metrics=metrics, spec=evaluation.selected,
                       activate=evaluation.promote, **common)
        if evaluation.promote:
            return JobOutcome(job.key, job.label, Outcome.PROMOTED, notes or "Passed evaluation and is now active.", version, **s)
        return JobOutcome(job.key, job.label, Outcome.KEPT_PREVIOUS, notes, version, **s)
    except Exception as exc:                                    # noqa: BLE001  (a failure must never escape half-done)
        log.error("analytics training failed for %s: %s", job.key.label, type(exc).__name__)
        reg.mark_error(run_id, f"Unexpected error: {type(exc).__name__}", now_utc)
        return JobOutcome(job.key, job.label, Outcome.ERROR, f"Unexpected error ({type(exc).__name__}); nothing was changed.", version)


def train(policy: Policy = DEFAULT_POLICY, now_utc: datetime | None = None, targets=None,
          dry_run: bool = False, trained_by: str = "cli") -> TrainingReport:
    from app.models.staff_credential import utcnow

    now_utc = now_utc or utcnow()
    prepared = prepare_all(now_utc, policy)
    overview = rd.assess(prepared, policy)
    report = TrainingReport(started_at=now_utc, dry_run=dry_run)
    for job in build_jobs(prepared, overview, targets):
        if not job.readiness.ready:
            report.outcomes.append(JobOutcome(job.key, job.label, Outcome.INSUFFICIENT, job.readiness.message))
            continue
        try:
            report.outcomes.append(_run_one(job, policy, now_utc, dry_run, trained_by))
        except ImportError:                                     # a missing package is a setup problem: say so, do not hide it
            raise
        except Exception as exc:                                # noqa: BLE001
            log.error("analytics training failed for %s: %s", job.key.label, type(exc).__name__)
            reg.db.session.rollback()
            report.outcomes.append(JobOutcome(job.key, job.label, Outcome.ERROR, f"Unexpected error ({type(exc).__name__})."))
    return report
