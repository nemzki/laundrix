"""Machine-learning layer for Analytics (forecasting and data readiness).

Descriptive analytics (the rest of ``app.analytics``) reports what already happened.  This package
is *predictive*: it estimates what may happen next, and only when the history supports it.

Layout
    policy.py           every threshold and rule, documented and configurable (edit here)
    schemas.py          constants and small dataclasses shared by the modules
    data_source.py      the ONLY module here that queries the database (aggregated SQL, no PII)
    data_preparation.py pure: turns aggregated rows into complete daily/weekly series
    data_validation.py  pure: data-quality checks (gaps, zero runs, invalid records)
    features.py         pure: leakage-safe lag / rolling / calendar features
    readiness.py        pure: decides INSUFFICIENT DATA vs READY FOR TRAINING and explains why
    cli.py              ``flask analytics-readiness`` (read-only)

Nothing in this package trains on a web request, and nothing here invents data.
"""
