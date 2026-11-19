# Laundrix – Unclaimed Order Prediction: Step-by-Step Guide

**What this adds:** one machine-learning model that gives every order waiting for pickup a
*disposal-risk score* (how likely it is to be left unclaimed until the shop disposes of it),
shown on the admin **Analytics & Reports** page. Nothing outside that page was changed.

> ⚠️ **Read this first – the outcomes in the updated CSV are simulated.**
> Your original CSV has no information about whether an order was picked up or disposed of.
> To make the model trainable I added `Status`, `Ready Date`, `Claimed Date`, `Disposed Date`,
> `Payment Status` and `Status Source`. Those values were generated with a fixed random seed
> and every row says `Status Source = simulated`. The page shows a warning while any training
> label is simulated. This proves the pipeline works; it says **nothing** about your real
> customers. Fill in real outcomes (Step 10) before using the scores for real decisions.

---

## How it works (the phases, in plain words)

1. **Data** – each past order needs a *label*: what finally happened to it (`claimed` or `disposed`).
   That is the "status of the order" you asked for. Orders still waiting are `unclaimed` and are
   *scored*, not used for training.
2. **Features** – four numbers per order: order total, paid-before-pickup (1/0),
   how many earlier orders that customer had, and ready-on-a-weekend (1/0).
   Names, phone numbers and IDs are **not** inputs (the name is only used to count earlier orders).
3. **Only "mature" orders are used for training** – ready at least `DISPOSAL_DAYS` (14) days ago,
   so we already know the final outcome. A 3-day-old order can't be "disposed" yet and would
   wrongly look "claimed".
4. **Train/test split by time** – the oldest 75 % trains the model, the newest 25 % tests it
   (like predicting the future from the past). Then the saved model is refit on all mature orders.
5. **Model** – logistic regression (one model). Its weights are saved as plain numbers in a new
   table `unclaimed_model_runs`, so it survives Render redeploys (Render's disk is wiped on deploy).
6. **Page** – scores the orders in *Ready for Pickup* (live) plus imported rows still waiting.

## What changed

| File | Change |
|---|---|
| `app/models/historical_transaction.py` | 5 new columns (outcome fields) |
| `app/models/unclaimed_model_run.py` | **new** table model for the saved model |
| `app/models/__init__.py` | exports the new models |
| `migrations/versions/c3a8e5f21d47_unclaimed_order_ml.py` | **new** migration (additive only) |
| `app/analytics/importers/historical_transactions.py` | reads/validates the new CSV columns |
| `app/analytics/importers/service.py` | can fill outcomes into rows you already imported |
| `app/analytics/ml/policy.py` `features.py` `model.py` `training.py` `predictions.py` | **new** ML code |
| `app/analytics/services.py` `routes.py` `__init__.py` | slimmed to unclaimed-order analytics; CLI `train` |
| `app/analytics/templates/analytics/index.html` | cleaned page (same shell, sidebar and styling) |
| `tests/analytics/test_unclaimed_model.py` | **new** tests |
| `washup_laundry_shop_history.csv` | updated CSV (same filename as before) |

Removed from the Analytics page: business overview, revenue/orders charts, payment methods,
popular services, historical revenue, dispatch queue, demo model, production-model card.

---

## Step-by-step

### Step 0 – Safety net
1. Make a fresh TiDB backup/export (your `.env` points at TiDB, so commands below run on your real database).
2. In your project folder: `git status` (should be clean), then `git checkout -b unclaimed-order-ml`.

### Step 1 – Copy the files
Copy the contents of the `laundrix_ml_update` folder over your project, keeping the same paths
(replace when asked). Do **not** copy the CSV into a folder that is committed to Git – it contains
customer first names. Keep it somewhere outside the repo, or add `*.csv` to `.gitignore`.

### Step 2 – Delete the old code this replaces
Delete these (they import modules that no longer exist and would break the app/tests):
```
app/analytics/ml/demo_training.py
app/analytics/ml/production_training.py
app/analytics/ml/dispatch_queue.py
app/analytics/ml/unclaimed_orders.py
tests/analytics/test_ml_training.py
tests/analytics/test_dispatch_queue.py
tests/analytics/test_unclaimed_order_readiness.py
tests/laundry/test_analytics_report.py
```

### Step 3 – Check the app still starts
```
flask check-db
flask --help
```
`flask --help` should list the `analytics` group. No new packages are needed
(`scikit-learn` is already in `requirements.txt`).

### Step 4 – Apply the database migration
```
flask db heads        # must show exactly one head: c3a8e5f21d47
flask db upgrade
```
This adds 5 columns to `historical_transactions` and creates `unclaimed_model_runs`.
Existing rows are untouched. **Do this before deploying the new code** – the new code reads the new columns.

### Step 5 – Dry-run the CSV import (writes nothing)
```
flask analytics import-history --file "PATH\TO\washup_laundry_shop_history.csv"
```
Expected, if you already imported the old CSV earlier under the same file name:
`CSV rows: 224`, `New records: 0`, `Existing records with outcome updates: 224`.
If you never imported it: `New records: 224`.
⚠️ The import source defaults to the **file name**. If you imported before with `--source SOMETHING`,
pass the same `--source` now, otherwise you will get a second copy of all 224 rows.

### Step 6 – Real import
Same command with `--execute` added.

### Step 7 – Train
```
flask analytics train
```
With the supplied CSV you should see roughly: 127 orders used, 23 disposed, test on 32 orders
(4 disposed), and a WARNING about simulated labels. Small differences are fine; an error
message such as "Not enough of each outcome" is also fine – it means the safety checks work.

### Step 8 – Look at the page (manual test)
Run `flask run`, sign in as admin, open **Analytics & Reports**. Check:
- Only 4 sections: overview, predictions, model details, pickup history.
- Sidebar, header and card styling match your other admin pages; dark/light theme still works.
- Predictions table lists "Imported history" rows (the 22 still-waiting ones) with risk scores/bands.
- Model details shows the yellow "Simulated outcomes" warning.
- Phone-size window: tables scroll sideways instead of breaking the page.
- Other pages (Dashboard, Orders, Payments, Staff) behave exactly as before.
- A non-admin account still gets "403 Forbidden" on `/admin/analytics/`.

### Step 9 – Test with a real order
Create a test order, move it step by step to **Ready for Pickup**, and reload Analytics: it appears as
"Live order" with a score. Move it to Picked Up: it disappears from the list.

### Step 10 – Replace the simulated data with real data (important)
In the CSV, for each order fill: `Payment Status` (paid/unpaid), `Ready Date`, `Status`
(claimed / disposed / unclaimed), `Claimed Date` or `Disposed Date`, and set
`Status Source` to `recorded`. Then repeat Steps 5–7 (the import updates existing rows, it does not duplicate).
Once every training row is `recorded`, the warning disappears by itself.

### Step 11 – Deploy to Render
```
git add -A
git commit -m "Analytics: unclaimed order disposal-risk model"
git push -u origin unclaimed-order-ml
```
Merge when happy; Render redeploys. Because the model lives in TiDB, nothing needs to be trained on Render.
Retrain whenever you import more records (`flask analytics train` from your computer).

### Rollback
`git revert` the commit (or redeploy the previous one). Optional database rollback:
`flask db downgrade` – it only drops the 5 new columns and the new table.

---

## Settings you may want to change (`app/analytics/ml/policy.py`)
- `DISPOSAL_DAYS = 14` → set your shop's real disposal rule. Retrain afterwards.
- `MIN_TRAINING_ORDERS = 100`, `MIN_PER_OUTCOME = 15` → minimum data before training is allowed.
- `HIGH_RISK = 0.70`, `MEDIUM_RISK = 0.40` → where the High/Medium bands start.

## Honest limits
- The model learns from imported history only. Live orders are scored but cannot become training
  data yet, because the Orders module has no "disposed" status (adding one would change other pages,
  which you asked me not to touch).
- With ~127 usable orders the test set is tiny (32 orders, 4 disposed). Treat metrics as rough.
- The model is tuned to *catch* disposed orders (class-balanced), so it flags more orders than will
  really be disposed; accuracy can be lower than "always guess claimed". The page shows that baseline.
- Scores rank orders by risk; they are not exact probabilities.

---

## Files and folders that are safe to delete
**Safe now (after Step 2):** the 8 files listed in Step 2.

**Safe (leftovers, not used by the app):**
- `results.txt` – an old pytest progress log.
- `README.txt` – a short "copy these files over" patch note, not project documentation.
- `instance/ml-development/` – the old demo model files (`instance/` is not in Git).
- All `__pycache__/` folders, `.pytest_cache/`, and `logs/*.log` (the `logs/.gitkeep` file must stay).

**Safe once you have a backup you trust (all ignored by Git, so they only take space locally):**
- `laundrix_backup.sql`, `laundrix_backup_before_audit.sql`.
- `database_backups/` – these are full dumps with real customer and staff data. Better to move them to
  a private backup location than to leave them in the project folder or in any zip you share.
  **Before removing it, open your `.env`:** if `DB_SSL_CA` points to `database_backups/isrgrootx1.pem`,
  keep that one `.pem` file (or move it and update `DB_SSL_CA`).

**Do NOT delete:** `app/`, `migrations/` (every file – the chain must stay complete), `config.py`,
`requirements.txt`, `.env`, `.gitignore`, `scripts/create_database.sql`, `docs/`, and
`frontend/src` (the source of your React pages).

**Probably removable but I did not change or verify them:** `frontend/tests/`, `frontend/playwright.*.config.ts`
(only needed if you run browser tests), and `frontend/src/prototype/`, `frontend/prototype.html`,
`frontend/foundation.html`. If you want a precise list, send the output of `git status --short`
and `git ls-files | head -200`.
