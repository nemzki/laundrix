from app.extensions import db
from app.models.staff_credential import utcnow


class UnclaimedModelRun(db.Model):
    """One trained version of the unclaimed-order (disposal risk) model.

    The model is a small logistic regression, so it is stored here as plain JSON numbers
    (no pickle/joblib files).  That keeps it in the database, which survives Render
    redeploys, and means it holds no customer data - only feature weights and metrics.
    """

    __tablename__ = "unclaimed_model_runs"
    __table_args__ = (db.UniqueConstraint("version", name="uq_unclaimed_model_runs_version"),)

    id = db.Column(db.Integer, primary_key=True)
    version = db.Column(db.Integer, nullable=False)
    is_active = db.Column(db.Boolean, nullable=False, default=False)
    algorithm = db.Column(db.String(40), nullable=False)
    features = db.Column(db.JSON, nullable=False)    # ordered feature names
    params = db.Column(db.JSON, nullable=False)      # mean, scale, coefficients, intercept
    metrics = db.Column(db.JSON, nullable=False)     # held-out test metrics
    n_orders = db.Column(db.Integer, nullable=False)
    n_disposed = db.Column(db.Integer, nullable=False)
    data_start = db.Column(db.Date)
    data_end = db.Column(db.Date)
    disposal_days = db.Column(db.Integer, nullable=False)
    labels_simulated = db.Column(db.Boolean, nullable=False, default=False)
    trained_at = db.Column(db.DateTime, nullable=False, default=utcnow)
