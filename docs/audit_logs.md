# Audit Logs: setup guide and developer notes

Admin-only **Audit Logs card** at the bottom of **Personal Settings** (`/settings`, below Account & Security). It shows 10 one-line entries, newest first; click a line for full details; filters are in a collapsed panel. The old URL `/admin/audit-logs/` only forwards admins to the card.

## 1. Install (step by step, Windows / PowerShell)

1. **Commit or stash your current work** so you can review exactly what this changes:
   ```powershell
   cd C:\Users\24-39\OneDrive\Desktop\laundrix
   git status
   git checkout -b feature/audit-logs
   ```
2. **Copy the package over the project.** Unzip `laundrix_audit_logs.zip` and copy its contents
   into the project root, choosing *Replace* when asked. Paths already match your project.
3. **Review what changed:**
   ```powershell
   git status
   git diff --stat
   ```
   Expect 12 modified files and the new `app/audit/`, `app/models/audit_log.py`,
   `migrations/versions/a9c4e2d7b1f3_audit_logs.py`, `tests/audit/`, `docs/audit_logs.md`.
4. **Back up the database** (the migration only *adds* a table, but always back up first):
   ```powershell
   mysqldump -u <user> -p laundrix_db > laundrix_backup_before_audit.sql
   ```
5. **Activate the venv and apply the migration:**
   ```powershell
   .\.venv\Scripts\Activate.ps1
   flask --app run db current       # should show b5d1e8c3a7f2 (head)
   flask --app run db upgrade       # creates the audit_logs table
   flask --app run db current       # should now show a9c4e2d7b1f3 (head)
   ```
6. **Run the tests:**
   ```powershell
   python -m pytest tests/audit -q
   python -m pytest -q
   ```
7. **Start the app, sign in as an administrator** and open your **Personal Settings** (gear icon by your name) and scroll to **Audit Logs**. Do something (create an order, change a service price) and refresh.
8. **Commit and push** (see your git workflow):
   ```powershell
   git add -A
   git commit -m "feat(audit): add admin audit logs"
   git push -u origin feature/audit-logs
   ```

No new Python packages and no new `.env` settings are required.

## 2. What is recorded

| Module | Events |
|---|---|
| Authentication | sign in (password, Google, Face Login), failed sign in, lockouts, sign out |
| Accounts & Staff | account created, enrollment, approve / reject / suspend / reactivate / deactivate, own-profile edits, CLI user creation |
| Orders | order created, status changes (including release / completion), laundry-received confirmation |
| Payments | payment recorded (with balance before/after, so partial payments show), reversals |
| Customers | created, edited (changed fields only; phone number masked) |
| Services & Pricing | service / package / extra created, edited, price changes (own action), activated / deactivated |
| Settings | payment settings, payment methods, payment QR |

Not in this codebase, so nothing to log yet: inventory, order cancellation, customer deletion,
role changes after creation, report exports. (`analytics` source was not in the zip you sent.)
When such features exist, add one `audit.record(...)` call to them (section 4).

## 3. Security and transaction design

* **Admin only.** `app/audit/routes.py` checks the role in a `before_request` hook for every URL in
  the blueprint. Staff get 403, anonymous users go to sign-in. The page has no write endpoints.
* **Append-only.** The ORM raises `AuditLogImmutableError` on any update/delete of an `AuditLog`.
  Optional database-level hardening: give the app's MySQL user only `SELECT, INSERT` on
  `audit_logs` (test this on a copy first; the migration/admin user keeps full rights).
* **Same transaction.** `record()` adds the row to the SQLAlchemy session; it is committed with the
  business change. If the audit insert fails, the whole operation rolls back and the request errors,
  so nothing "succeeds" without its record. Failed sign-ins use `commit=True`.
  *One deliberate exception:* sign-out always completes; if its record fails, the error is logged.
* **No secrets.** Keys containing password, hash, token, secret, api key, credential, session,
  cookie, signature, csrf, biometric, otp, pin... are dropped before saving. Phone numbers and
  e-mails are masked. Only e-mail-looking identifiers typed at a failed sign-in are kept (so a
  password typed in the wrong box is never stored). Payment account details are never copied.
* **Safe filters.** All filters are validated (whitelists / strict date formats) and run as SQL.
  Text search uses an escaped `LIKE`. Output is HTML-escaped.
* **Times** are stored in UTC and shown/filtered in Philippine time (UTC+8), like the rest of Laundrix.

## 4. Logging something new

```python
from app.audit import services as audit

audit.record(audit.AuditAction.UPDATE, audit.AuditModule.CUSTOMERS,
             "Updated customer Ana", resource_id=customer.id,
             resource_label=f"Customer {customer.full_name}", old=old, new=new)
db.session.commit()   # same commit as the change
```
Use `audit.snapshot(obj, FIELDS)` before and after a change and `audit.changes(old, new)` to keep only
what changed. New actions/modules go in `AuditAction` / `AuditModule` in `app/audit/services.py`
and automatically appear in the filter drop-downs.

Existing logs feed the audit log automatically: `app.core.audit.record_event` (auth/accounts) and
`app.payments.services.log_event` (payments) also write an audit row, so their call sites did not change.

## 5. Notes

* The old `auth_events` and `payment_events` tables are kept as they were (staff detail pages use them).
* Search by name uses a contains-match that cannot use an index; fine for shop-scale data. If the table
  grows into the millions, add a prefix search or an archive job.
* Rolling back: `flask --app run db downgrade` drops `audit_logs` (deleting the trail), then revert the code.
