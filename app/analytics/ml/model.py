"""A tiny logistic-regression model that is stored as plain numbers (JSON).

scikit-learn does the fitting. Predictions use the stored numbers only, so no pickle/joblib
file is needed and the model lives safely in the database.
"""
import math

# numpy / scikit-learn are imported inside fit() and evaluate() on purpose: they are only
# needed when training, so the Analytics page (which only calls predict_probability) stays light.

ALGORITHM = "logistic_regression"


def fit(x, y):
    """Fit on feature rows x and labels y (1 = disposed). Returns JSON-safe parameters."""
    import numpy as np
    from sklearn.linear_model import LogisticRegression
    from sklearn.preprocessing import StandardScaler

    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=int)
    scaler = StandardScaler().fit(x)
    classifier = LogisticRegression(class_weight="balanced", max_iter=1000)
    classifier.fit(scaler.transform(x), y)
    return {
        "mean": [float(v) for v in scaler.mean_],
        "scale": [float(v) for v in scaler.scale_],
        "coefficients": [float(v) for v in classifier.coef_[0]],
        "intercept": float(classifier.intercept_[0]),
    }


def predict_probability(params, vector):
    """Disposal-risk score (0..1) for one feature vector."""
    z = params["intercept"]
    for value, mean, scale, weight in zip(
        vector, params["mean"], params["scale"], params["coefficients"]
    ):
        z += weight * ((value - mean) / (scale or 1.0))
    z = max(-30.0, min(30.0, z))
    return 1.0 / (1.0 + math.exp(-z))


def evaluate(params, x, y):
    """Metrics on data the model was NOT trained on."""
    import numpy as np
    from sklearn.metrics import accuracy_score, f1_score, precision_score, recall_score, roc_auc_score

    y = np.asarray(y, dtype=int)
    scores = np.asarray([predict_probability(params, row) for row in x])
    predicted = (scores >= 0.5).astype(int)
    return {
        "accuracy": round(float(accuracy_score(y, predicted)), 4),
        "precision": round(float(precision_score(y, predicted, zero_division=0)), 4),
        "recall": round(float(recall_score(y, predicted, zero_division=0)), 4),
        "f1": round(float(f1_score(y, predicted, zero_division=0)), 4),
        "roc_auc": round(float(roc_auc_score(y, scores)), 4),
        "test_orders": int(len(y)),
        "test_disposed": int(y.sum()),
        # What you would score by guessing "claimed" for everything.
        "baseline_accuracy": round(float(1 - y.mean()), 4),
    }
