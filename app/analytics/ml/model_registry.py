"""Model registry: versioned, checksummed, database-backed (no pickle, no files, no paths).

A stored model is a row in ``analytics_model_runs`` holding the algorithm name and plain-number
parameters.  Loading validates the row before it can be used: schema version, integrity checksum,
algorithm, feature configuration and parameter shapes.  A missing, corrupted or incompatible model
raises ``ModelLoadError`` and the caller shows "unavailable"; it never crashes the application and
never falls back to an unvalidated model.

Status derivation (``derive_status``) combines the data-driven readiness with the registry:
    TRAINING            a run is in progress
    TRAINED             an active, loadable model exists and the data has not moved on much
    MODEL OUTDATED      the active model is unusable (corrupt/incompatible) or the data has advanced by
                        >= ``outdated_after_horizons`` forecast horizons past its training data
    EVALUATION FAILED   no active model and the latest run did not meet the criteria
    READY FOR TRAINING  enough data, nothing trained yet
    INSUFFICIENT DATA   not enough data
    NOT TRAINED         readiness unknown and nothing trained
"""
from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError

from app.analytics.ml import forecasting as fc
from app.analytics.ml.features import config_for
from app.analytics.ml.policy import DEFAULT_POLICY, Policy
from app.analytics.ml.schemas import ModelStatus
from app.extensions import db
from app.models import AnalyticsModelRun, ModelRunStatus

SCHEMA_VERSION = 1
_ENTITY_MAX = 160


class TrainingInProgress(RuntimeError):
    """Another training run for the same model is already active."""


class ModelLoadError(ValueError):
    """A stored model cannot be trusted or used.  The message is safe to show (no paths, no secrets)."""


@dataclass(frozen=True)
class ModelKey:
    target: str
    granularity: str
    entity: str = ""

    @property
    def stored_entity(self) -> str:
        if len(self.entity) <= _ENTITY_MAX:
            return self.entity
        return self.entity[:_ENTITY_MAX - 9] + "#" + hashlib.sha1(self.entity.encode("utf-8")).hexdigest()[:8]

    @property
    def label(self) -> str:
        return f"{self.target}/{self.granularity}" + (f"/{self.entity}" if self.entity else "")


def _match(key: ModelKey):
    R = AnalyticsModelRun
    return (R.target == key.target, R.granularity == key.granularity, R.entity == key.stored_entity)


# ----------------------------------------------------------------------------- integrity

def canonical(key: ModelKey, algorithm: str, kind: str, params: dict, feature_config, schema_version: int) -> str:
    return json.dumps({"key": [key.target, key.granularity, key.stored_entity], "algorithm": algorithm, "kind": kind,
                       "params": params, "feature_config": feature_config, "schema_version": schema_version},
                      sort_keys=True, separators=(",", ":"), allow_nan=False)


def checksum_for(key: ModelKey, algorithm: str, kind: str, params: dict, feature_config, schema_version: int = SCHEMA_VERSION) -> str:
    return hashlib.sha256(canonical(key, algorithm, kind, params, feature_config, schema_version).encode("utf-8")).hexdigest()


def load_model(run: AnalyticsModelRun) -> fc.ModelSpec:
    """Validate a stored run and return its ModelSpec, or raise ModelLoadError."""
    if run is None or run.status != ModelRunStatus.TRAINED:
        raise ModelLoadError("There is no trained model for this forecast.")
    if run.schema_version != SCHEMA_VERSION:
        raise ModelLoadError("The stored model was created by an incompatible version and must be retrained.")
    if not run.algorithm or run.kind not in (fc.Kind.BASELINE, fc.Kind.ML) or not isinstance(run.params, dict):
        raise ModelLoadError("The stored model is incomplete and must be retrained.")
    key = ModelKey(run.target, run.granularity, run.entity)
    try:
        expected = checksum_for(key, run.algorithm, run.kind, run.params, run.feature_config, run.schema_version)
    except (TypeError, ValueError):
        raise ModelLoadError("The stored model is corrupted and must be retrained.") from None
    if run.checksum != expected:
        raise ModelLoadError("The stored model failed its integrity check and must be retrained.")

    if run.algorithm == "ridge":
        if run.kind != fc.Kind.ML:
            raise ModelLoadError("The stored model is inconsistent and must be retrained.")
        p = run.params
        try:
            names = list(p["feature_names"])
            arrays = [p["mean"], p["scale"], p["coef"]]
            numbers = [*p["mean"], *p["scale"], *p["coef"], p["intercept"]]
            date.fromisoformat(p["series_start"])
        except (KeyError, TypeError, ValueError):
            raise ModelLoadError("The stored model is corrupted and must be retrained.") from None
        if names != config_for(run.granularity).feature_names() or run.feature_config != config_for(run.granularity).as_dict():
            raise ModelLoadError("The stored model uses a different feature set and must be retrained.")
        if any(len(a) != len(names) for a in arrays) or not all(isinstance(v, (int, float)) and math.isfinite(v) for v in numbers):
            raise ModelLoadError("The stored model is corrupted and must be retrained.")
    elif run.algorithm not in fc.BASELINES.get(run.granularity, ()) or run.kind != fc.Kind.BASELINE:
        raise ModelLoadError("The stored model uses an unknown algorithm and must be retrained.")
    return fc.ModelSpec(run.algorithm, run.kind, dict(run.params))


# ----------------------------------------------------------------------------- persistence

def active_run(key: ModelKey) -> AnalyticsModelRun | None:
    R = AnalyticsModelRun
    return db.session.scalars(select(R).where(*_match(key), R.is_active.is_(True), R.status == ModelRunStatus.TRAINED)
                              .order_by(R.version.desc()).limit(1)).first()


def latest_run(key: ModelKey) -> AnalyticsModelRun | None:
    R = AnalyticsModelRun
    return db.session.scalars(select(R).where(*_match(key)).order_by(R.version.desc()).limit(1)).first()


def list_runs(key: ModelKey, limit: int = 20) -> list[AnalyticsModelRun]:
    R = AnalyticsModelRun
    return list(db.session.scalars(select(R).where(*_match(key)).order_by(R.version.desc()).limit(limit)))


def training_in_progress(key: ModelKey, now_utc: datetime, lock_minutes: int) -> bool:
    R = AnalyticsModelRun
    cutoff = now_utc - timedelta(minutes=lock_minutes)
    return db.session.scalars(select(R.id).where(*_match(key), R.status == ModelRunStatus.TRAINING,
                                                  R.started_at >= cutoff).limit(1)).first() is not None


def begin_run(key: ModelKey, *, trained_by: str, now_utc: datetime, lock_minutes: int) -> AnalyticsModelRun:
    """Open a new versioned run (status 'training').  This row is the training lock."""
    R = AnalyticsModelRun
    cutoff = now_utc - timedelta(minutes=lock_minutes)
    for stale in db.session.scalars(select(R).where(*_match(key), R.status == ModelRunStatus.TRAINING)):
        if stale.started_at >= cutoff:
            raise TrainingInProgress(f"Training for {key.label} is already in progress.")
        stale.status = ModelRunStatus.ERROR
        stale.message = "Abandoned training run (it exceeded the allowed time)."
        stale.finished_at = now_utc
    version = (db.session.scalar(select(func.max(R.version)).where(*_match(key))) or 0) + 1
    run = R(target=key.target, granularity=key.granularity, entity=key.stored_entity, version=version,
            status=ModelRunStatus.TRAINING, is_active=False, trained_by=trained_by[:64], started_at=now_utc,
            schema_version=SCHEMA_VERSION)
    db.session.add(run)
    try:
        db.session.commit()
    except IntegrityError:                     # unique (key, version): another process won the race
        db.session.rollback()
        raise TrainingInProgress(f"Training for {key.label} was just started elsewhere.") from None
    return run


def finish_run(run: AnalyticsModelRun, *, status: str, now_utc: datetime, message: str = "",
               spec: fc.ModelSpec | None = None, metrics: dict | None = None, data_start: date | None = None,
               data_end: date | None = None, n_observations: int | None = None, n_events: int | None = None,
               activate: bool = False) -> None:
    """Record the outcome of a run; with ``activate`` also make it the single active model, atomically."""
    if activate and (status != ModelRunStatus.TRAINED or spec is None):
        raise ValueError("Only a trained run with a model can be activated.")
    key = ModelKey(run.target, run.granularity, run.entity)
    run.status = status
    run.message = (message or "")[:500] or None
    run.metrics = metrics
    run.data_start, run.data_end, run.n_observations, run.n_events = data_start, data_end, n_observations, n_events
    run.finished_at = now_utc
    if spec is not None:
        feature_config = config_for(run.granularity).as_dict() if spec.algorithm == "ridge" else None
        run.algorithm, run.kind, run.params, run.feature_config = spec.algorithm, spec.kind, spec.params, feature_config
        run.schema_version = SCHEMA_VERSION
        run.checksum = checksum_for(key, spec.algorithm, spec.kind, spec.params, feature_config, SCHEMA_VERSION)
    if activate:
        R = AnalyticsModelRun
        db.session.execute(update(R).where(*_match(key), R.id != run.id, R.is_active.is_(True)).values(is_active=False))
        run.is_active = True
    db.session.commit()


def mark_error(run_id: int, message: str, now_utc: datetime) -> None:
    """Record an unexpected failure.  Safe to call after a rollback."""
    db.session.rollback()
    run = db.session.get(AnalyticsModelRun, run_id)
    if run is not None and run.status == ModelRunStatus.TRAINING:
        run.status = ModelRunStatus.ERROR
        run.message = message[:500]
        run.finished_at = now_utc
        db.session.commit()


# ----------------------------------------------------------------------------- status

def is_outdated(data_end: date | None, series_end: date | None, granularity: str, policy: Policy = DEFAULT_POLICY) -> bool:
    """True once the data has advanced >= outdated_after_horizons forecast horizons past the model's data."""
    if data_end is None or series_end is None:
        return False
    steps_behind = (series_end - data_end) / fc.step_of(granularity)
    return steps_behind >= policy.rule(granularity).horizon * policy.outdated_after_horizons


def derive_status(*, ready: bool | None, training: bool, has_active: bool, active_usable: bool,
                  outdated: bool, latest_failed: bool) -> str:
    """Pure decision table (see module docstring)."""
    if training:
        return ModelStatus.TRAINING
    if has_active:
        return ModelStatus.OUTDATED if (not active_usable or outdated) else ModelStatus.TRAINED
    if latest_failed:
        return ModelStatus.EVALUATION_FAILED
    if ready is True:
        return ModelStatus.READY_FOR_TRAINING
    if ready is False:
        return ModelStatus.INSUFFICIENT_DATA
    return ModelStatus.NOT_TRAINED


@dataclass(frozen=True)
class KeyStatus:
    key: ModelKey
    status: str
    message: str
    usable: bool
    version: int | None = None
    algorithm: str | None = None
    kind: str | None = None
    trained_at: datetime | None = None
    data_end: date | None = None

    def as_dict(self) -> dict:
        return {"target": self.key.target, "granularity": self.key.granularity, "entity": self.key.entity or None,
                "status": self.status, "status_label": ModelStatus.LABELS[self.status], "message": self.message,
                "usable": self.usable, "version": self.version, "algorithm": self.algorithm, "kind": self.kind,
                "trained_at": self.trained_at.isoformat() if self.trained_at else None,
                "data_end": self.data_end.isoformat() if self.data_end else None}


def key_status(key: ModelKey, *, ready: bool | None, series_end: date | None, now_utc: datetime,
               policy: Policy = DEFAULT_POLICY) -> tuple[KeyStatus, fc.ModelSpec | None, AnalyticsModelRun | None]:
    """Status for one key, its validated model (None when unusable) and the active run row (for metrics)."""
    training = training_in_progress(key, now_utc, policy.training_lock_minutes)
    run = active_run(key)
    latest = latest_run(key)
    spec, load_problem = None, None
    if run is not None:
        try:
            spec = load_model(run)
        except ModelLoadError as exc:
            load_problem = str(exc)
    outdated = bool(run is not None and spec is not None and is_outdated(run.data_end, series_end, key.granularity, policy))
    status = derive_status(ready=ready, training=training, has_active=run is not None, active_usable=spec is not None,
                           outdated=outdated, latest_failed=bool(latest and latest.status == ModelRunStatus.EVALUATION_FAILED))
    if load_problem:
        msg = load_problem
    elif status == ModelStatus.OUTDATED:
        msg = "New data has arrived since this model was trained. Retraining is recommended."
    elif status == ModelStatus.EVALUATION_FAILED:
        msg = (latest.message or "The latest model did not meet the evaluation criteria.")
    else:
        msg = ""
    return KeyStatus(key, status, msg, spec is not None, run.version if run else None, run.algorithm if run else None,
                     run.kind if run else None, run.finished_at if run else None, run.data_end if run else None), spec, run
