"""Business rules and thresholds for the unclaimed-order model.

Change a value here, then retrain with `flask analytics train`.
"""

# How many days after an order is ready for pickup the shop disposes of it if nobody claims it.
# Set this to YOUR shop's real rule.
DISPOSAL_DAYS = 14

# The model refuses to train on less data than this (a model built on a handful of orders
# would only look smart). Only "mature" orders count: ready at least DISPOSAL_DAYS ago, so
# the outcome (claimed or disposed) is already known.
MIN_TRAINING_ORDERS = 100
MIN_PER_OUTCOME = 15          # at least this many claimed AND this many disposed

# The newest part of the data (by ready date) is kept aside to test the model honestly.
TEST_FRACTION = 0.25

# Risk bands shown on the page (the score is a model score, not a guaranteed probability).
HIGH_RISK = 0.70
MEDIUM_RISK = 0.40
