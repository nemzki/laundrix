# Analytics & Reports – system-trained model, charts and CSV export

## How the model gets its data (no synthetic or imported data)
An order becomes a training example only when **Laundrix itself confirms its outcome**:
- **Picked up** – its status history shows it moved to *Picked Up / Released* (or *Completed*) after *Ready for Pickup*.
- **Disposed** – an admin pressed **Mark disposed** on the Analytics page.

It must also be **mature**: ready at least `DISPOSAL_DAYS` (30) days ago. Orders still waiting, or waiting
longer than that with nothing recorded, are **never** used as labels. They are reported as
"N orders have waited more than 30 days with no outcome recorded".

Inputs (all known when the order became ready, so nothing leaks the answer): order total, whether it was fully
paid *by the time it became ready*, how many earlier orders the customer had, and whether it was ready on a weekend.
Names, phone numbers and IDs are not inputs.

## When it trains
Every time an admin opens Analytics the page checks readiness (`app/analytics/ml/policy.py`):
| Rule | Default |
|---|---|
| Confirmed, mature orders | at least 100 |
| Picked-up orders / disposed orders | at least 10 of each |
| Retrain automatically after | 10 new confirmed orders |
| Model is used only if ROC-AUC on the newest orders is at least | 0.60 |

- Not enough data → "Machine learning is not ready. More order records are needed for reliable training." with progress bars. **No scores are shown.**
- Trained but not better than chance → "Not reliable yet". **No scores are shown.**
- Reliable → status, training records, accuracy/recall/precision/ROC-AUC and a risk score on every waiting order.
- `flask analytics train` does the same from the command line.
The imported-CSV model (simulated outcomes) is no longer used anywhere on the page.

## Realistic expectation
Real disposals are rare, so reaching 10 disposed orders may take a while. Keep recording outcomes:
move orders to *Picked Up* as customers collect them, and press **Mark disposed** when the shop disposes of laundry.

## Charts (last 7 / 30 / 90 days)
Orders per day, revenue per day (payments received minus reversals), order status distribution (all orders)
and most used services (orders containing each service or package). Drawn with the Chart.js copy already in
`app/core/static/vendor/chartjs` (no CDN, no inline scripts).

## CSV export (admin only)
Analytics → **Export data**: Orders, Order items/services, or Payments for a date range (max 366 days, 20,000 rows).
UTF-8 with BOM so Excel opens it correctly; formulas in text are neutralised; **customer phone numbers are not exported**;
every export is written to the audit log (new action "Data export").

## Install
1. Copy the files in this folder over your project (same paths).
2. `flask db heads` → must show exactly one head: `f7b2d9a4c1e8`.
3. Run on your local database first: `flask db upgrade`, then `python -m pytest tests/analytics tests/laundry/test_analytics_system.py tests/laundry/test_admin_dashboard_ui.py -q`
4. `flask run`, sign in as admin, open Analytics & Reports and check every section, the 7/30/90 buttons, a CSV download opened in Excel, light and dark theme.
5. Optional clean-up of the earlier simulated rows (dry-run first):
   `flask analytics purge-simulated` then `flask analytics purge-simulated --execute`
6. For TiDB: take a backup, switch `.env` to TiDB, `flask check-db`, `flask db current`, `flask db upgrade`, then restore your local `.env`, commit and push. Run the migration **before** the new code deploys.
