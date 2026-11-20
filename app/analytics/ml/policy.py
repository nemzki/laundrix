"""Business rules and thresholds for the unclaimed-order model.

Change a value here and the page applies it on the next visit (no retraining command needed).
"""

# How many days after an order becomes "Ready for Pickup" the shop disposes of it if nobody
# claims it. Set this to YOUR shop's real rule.
DISPOSAL_DAYS = 14

# --- when is there enough real data to train? -------------------------------------------------
# Only "mature" orders count: ready at least DISPOSAL_DAYS ago AND with a confirmed outcome
# (picked up, or marked disposed by an admin). Orders still waiting are never used as labels.
MIN_TRAINING_ORDERS = 100     # confirmed orders needed in total
MIN_PER_OUTCOME = 10          # at least this many picked up AND this many disposed

# Retrain automatically once this many NEW confirmed orders have appeared since the last training.
RETRAIN_AFTER_NEW = 10

# The newest part of the data (by ready time) is kept aside to test the model honestly.
TEST_FRACTION = 0.25

# A trained model is only used for predictions if it ranks held-out orders better than chance.
# ROC-AUC 0.5 = coin flip. Below this the page says the model is not reliable and shows no scores.
MIN_ROC_AUC = 0.60

# Risk bands shown on the page (a model score, not a guaranteed probability).
HIGH_RISK = 0.70
MEDIUM_RISK = 0.40
