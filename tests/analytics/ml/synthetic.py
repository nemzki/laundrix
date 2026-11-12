"""Deterministic SYNTHETIC series used only to test the forecasting machinery.

They are never business data and never appear in the application.  "trend" has a weekday pattern plus
growth (a structured series a model can learn); "noise" has no structure at all (nothing can beat the average).
"""
from datetime import date

import numpy as np

D0 = date(2026, 7, 6)                                    # a Monday
WEEK = np.array([4, 5, 6, 5, 8, 10, 3], float)


def counts(kind: str, seed: int, days: int):
    """Orders per day for ``days`` consecutive days starting at D0 (the first day always has an order)."""
    i = np.arange(days)
    lam = 0.5 * WEEK[i % 7] + 0.05 * i if kind == "trend" else np.full(days, 3.0)
    c = np.random.default_rng(seed).poisson(lam).astype(int)
    c[0] = max(1, c[0])
    return c
