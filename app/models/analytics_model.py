from app.extensions import db
from app.models.staff_credential import utcnow


class ModelRunStatus:
    """Outcome of one training run (the registry row).  Whether it is the ACTIVE model is ``is_active``."""
    TRAINING = "training"                      # in progress (doubles as the training lock)
    TRAINED = "trained"                        # passed evaluation and was saved
    EVALUATION_FAILED = "evaluation_failed"    # did not meet the documented criteria; nothing was activated
    ERROR = "error"                            # unexpected failure (or an abandoned run)
    ALL = (TRAINING, TRAINED, EVALUATION_FAILED, ERROR)


class AnalyticsModelRun(db.Model):
    """One training run of one forecasting target, kept forever as an audit trail.

    Holds only aggregate, non-personal data: algorithm name, coefficients (plain JSON numbers, never a
    pickle), evaluation metrics and the date range trained on.  At most ONE run per
    (target, granularity, entity) is active; the application enforces that inside one transaction.
    ``checksum`` lets the loader detect a corrupted or tampered row.
    """
    __tablename__ = "analytics_model_runs"
    __table_args__ = (
        db.UniqueConstraint("target", "granularity", "entity", "version", name="uq_analytics_model_runs_key_version"),
        db.CheckConstraint("granularity IN ('day', 'week')", name="ck_analytics_model_runs_granularity"),
        db.CheckConstraint("status IN ('training', 'trained', 'evaluation_failed', 'error')",
                           name="ck_analytics_model_runs_status"),
        db.CheckConstraint("version >= 1", name="ck_analytics_model_runs_version"),
        db.CheckConstraint("is_active = 0 OR status = 'trained'", name="ck_analytics_model_runs_active_trained"),
        db.Index("ix_analytics_model_runs_key_active", "target", "granularity", "entity", "is_active"),
    )

    id = db.Column(db.Integer, primary_key=True)
    target = db.Column(db.String(40), nullable=False)
    granularity = db.Column(db.String(10), nullable=False)
    entity = db.Column(db.String(160), nullable=False, default="", server_default="")   # service/package key; '' otherwise
    version = db.Column(db.Integer, nullable=False)                                      # 1, 2, 3 ... per key
    status = db.Column(db.String(20), nullable=False, default=ModelRunStatus.TRAINING)
    is_active = db.Column(db.Boolean, nullable=False, default=False)

    algorithm = db.Column(db.String(40))                  # e.g. 'ridge', 'weekday_mean_4'
    kind = db.Column(db.String(10))                       # 'ml' or 'baseline'
    params = db.Column(db.JSON)                           # fitted numbers only
    feature_config = db.Column(db.JSON)
    metrics = db.Column(db.JSON)                          # backtest results, criteria, champion check
    schema_version = db.Column(db.Integer, nullable=False, default=1)
    checksum = db.Column(db.String(64))                   # sha256 of the canonical model description

    data_start = db.Column(db.Date)
    data_end = db.Column(db.Date)
    n_observations = db.Column(db.Integer)
    n_events = db.Column(db.Integer)
    message = db.Column(db.String(500))                   # why it failed / was not promoted / notes
    trained_by = db.Column(db.String(64))                 # 'cli'
    started_at = db.Column(db.DateTime, nullable=False, default=utcnow)
    finished_at = db.Column(db.DateTime)

    def __repr__(self):
        return f"<AnalyticsModelRun {self.target}/{self.granularity}/{self.entity or '-'} v{self.version} {self.status}>"
