# Laundrix

Laundrix is a laundry-shop management system built with **Python, Flask and MySQL/TiDB**. It covers the whole
counter workflow (customers, orders, payments, pickup, SMS), a public QR order-tracking page, admin and staff
portals with optional government-ID and face verification, and an admin analytics page with a small machine-learning
model that flags orders likely to go unclaimed.

> **Never commit** `.env`, API keys, OAuth secrets, database passwords, real customer data, database dumps,
> or identity-verification data. Only `.env.example` belongs in Git.

---

## Table of contents

1. [Features](#1-features)
2. [Tech stack](#2-tech-stack)
3. [Project structure](#3-project-structure)
4. [Prerequisites](#4-prerequisites)
5. [Local setup, step by step](#5-local-setup-step-by-step)
6. [Environment variables](#6-environment-variables)
7. [Configure external services](#7-configure-external-services)
8. [First-run data and accounts](#8-first-run-data-and-accounts)
9. [Using the app](#9-using-the-app)
10. [Analytics and the unclaimed-order model](#10-analytics-and-the-unclaimed-order-model)
11. [Frontend (React) bundles](#11-frontend-react-bundles)
12. [CLI command reference](#12-cli-command-reference)
13. [Testing](#13-testing)
14. [Deploying to Render + TiDB Cloud](#14-deploying-to-render--tidb-cloud)
15. [Operations and maintenance](#15-operations-and-maintenance)
16. [Security notes](#16-security-notes)
17. [Troubleshooting](#17-troubleshooting)
18. [Git workflow](#18-git-workflow)
19. [Further documentation](#19-further-documentation)

---

## 1. Features

| Area | What it does |
|---|---|
| **Orders** | 6-step New Order wizard (Services, Details, Extras, Customer, Payment, Review), printable order stub with a locally generated QR code, status changes with history, customer directory |
| **Payments** | Manual payment ledger (Cash, GCash, custom methods), partial / full / pay-later, admin-only reversals, outstanding balances, daily/weekly/monthly summary |
| **Public tracking** | `/track/<token>` shows an order's status and balance to the customer via an unguessable token |
| **SMS** | One UniSMS text per order when it first reaches *Ready for Pickup*, only with per-order customer consent |
| **Catalog** | Admin management of services, packages and add-ons |
| **Admin sign-in** | Username/email + password, or Google OAuth |
| **Staff sign-in** | Email + password, Google, or **Face Login** (Didit liveness + face search) |
| **Identity verification** | Government ID + liveness + face match through Didit's hosted flow (optional) |
| **Staff management** | Admin creates, approves, suspends and re-enrolls staff accounts |
| **Audit log** | Admin-only log of sensitive actions (`/admin/audit-logs`) |
| **Analytics** | Admin charts, CSV export and an unclaimed-order disposal-risk model (`/admin/analytics`) |
| **Security** | CSRF, rate limiting, strict CSP, secure cookies, account-status gate on every request |

## 2. Tech stack

- **Backend:** Python, Flask 3, Flask-SQLAlchemy, Flask-Migrate (Alembic), Flask-Login, Flask-WTF, Flask-Limiter, Flask-Talisman, Authlib
- **Database:** MySQL 8 locally, TiDB Cloud (MySQL compatible) in production, via PyMySQL
- **ML:** scikit-learn / NumPy (model parameters are stored in the database, not on disk)
- **Frontend:** server-rendered Jinja templates plus React 19 / TypeScript / Vite / Tailwind bundles for the dashboard, orders, catalog and staff pages
- **Integrations:** Google OAuth, Didit (identity), UniSMS (SMS)
- **Production server:** Gunicorn on Render

## 3. Project structure

```text
laundrix/
├── app/
│   ├── __init__.py          # application factory (create_app)
│   ├── extensions.py        # db, migrate, csrf, limiter, login, oauth, talisman
│   ├── cli.py               # check-db, create-user (+ registers other CLI groups)
│   ├── analytics/           # /admin/analytics, charts, CSV export, ML (app/analytics/ml)
│   ├── audit/               # /admin/audit-logs
│   ├── auth/                # admin login, Google OAuth, bootstrap-admin
│   ├── catalog/             # /admin/services (services, packages, add-ons)
│   ├── core/                # shared templates, static files, built React bundles, helpers
│   ├── dashboard/           # /dashboard
│   ├── identity/            # Didit identity verification, face search, webhook
│   ├── landing/             # public landing page (/)
│   ├── models/              # SQLAlchemy models
│   ├── orders/              # customers, orders, pricing, stubs
│   ├── payments/            # payment ledger, settings, outstanding balances
│   ├── sms/                 # UniSMS provider, phone validation
│   ├── staff_admin/         # /admin/staff
│   ├── staff_auth/          # /staff enrollment and staff sign-in
│   └── tracking/            # public QR order tracking
├── docs/                    # deeper technical guides (see section 19)
├── frontend/                # React/TypeScript source (Vite). Builds into app/core/static/
├── migrations/versions/     # Alembic revision history
├── scripts/create_database.sql
├── tests/                   # pytest suite (+ frontend browser tests under frontend/tests)
├── config.py                # all settings, read from .env
├── run.py                   # entry point: `app = create_app()`
├── requirements.txt
├── .python-version
└── .env.example             # template for your private .env
```

## 4. Prerequisites

| Tool | Why | Notes |
|---|---|---|
| **Git** | Clone and push code | <https://git-scm.com/downloads> |
| **Python 3.14** | Run Flask | Version in `.python-version`; check with `python --version` |
| **MySQL 8** (local) | Development database | Or point at TiDB Cloud instead (section 14) |
| **MySQL Workbench** (optional) | Run `scripts/create_database.sql` | Any MySQL client works |
| **Node.js (current LTS)** | *Only if you change the React frontend* | The built bundles are already committed |

Check what you have:

```powershell
git --version
python --version
python -m pip --version
```

## 5. Local setup, step by step

Commands are shown for **Windows PowerShell**. On macOS/Linux use the bash equivalents noted beside them.

### Step 1. Clone the repository

```powershell
git clone YOUR_GITHUB_REPOSITORY_URL
cd laundrix
```

### Step 2. Create and activate a virtual environment

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

macOS/Linux: `python3 -m venv .venv && source .venv/bin/activate`

If PowerShell blocks activation, allow it for this window only, then activate again:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
```

You should see `(.venv)` in the prompt.

### Step 3. Install the Python dependencies

```powershell
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

Re-run the second command whenever `requirements.txt` changes.

### Step 4. Create the local database

1. Start MySQL Server.
2. Open `scripts/create_database.sql`. **Replace `CHANGE_ME_TO_A_STRONG_UNIQUE_PASSWORD`** with your own password. Never commit that change.
3. Run the script as a MySQL admin (Workbench, or `mysql -u root -p < scripts/create_database.sql`).

This creates the `laundrix_db` database (`utf8mb4`) and a least-privilege `laundrix_user`.

### Step 5. Create your `.env`

```powershell
Copy-Item .env.example .env
```

macOS/Linux: `cp .env.example .env`

Generate a secret key and paste it into `SECRET_KEY`:

```powershell
python -c "import secrets; print(secrets.token_hex(32))"
```

Minimum working local configuration:

```env
APP_ENV=development
SECRET_KEY=<the value you just generated>
APP_BASE_URL=http://127.0.0.1:5000
BEHIND_PROXY=false

DB_HOST=localhost
DB_PORT=3306
DB_NAME=laundrix_db
DB_USER=laundrix_user
DB_PASSWORD=<the password you set in Step 4>
```

Everything else is optional and can stay at its default (SMS, identity verification and Google sign-in are off or unconfigured). See [section 6](#6-environment-variables) for every variable.

### Step 6. Check the database connection

```powershell
python -m flask --app run check-db
```

Expected: `Connected to 'laundrix_db' (MySQL 8.x)`.

### Step 7. Apply the database migrations

```powershell
python -m flask --app run db heads      # must print exactly ONE head: a1d5c8e3b7f2
python -m flask --app run db upgrade
python -m flask --app run db current    # should now show a1d5c8e3b7f2 (head)
```

Never run `flask db init` on this project, and never edit the `alembic_version` table by hand. If you see two heads, stop and ask before merging.

### Step 8. Seed starting data

```powershell
python -m flask --app run seed-catalog     # starter services, packages and add-ons
python -m flask --app run seed-payments    # Cash and GCash methods + the payment-settings row
```

Both are safe to run again; they do not overwrite existing rows.

### Step 9. Create the first administrator

Choose **one** way.

**A. Username + password (works without Google).** Set these in `.env`, then run the command:

```env
INITIAL_ADMIN_USERNAME=admin
INITIAL_ADMIN_PASSWORD=<a strong unique password>
INITIAL_ADMIN_EMAIL=you@example.com
```

```powershell
python -m flask --app run bootstrap-admin
```

Then **delete `INITIAL_ADMIN_PASSWORD` from `.env`**. Sign in at `/auth/admin`.

**B. Google account.** Configure Google OAuth first ([section 7.1](#71-google-oauth)), then:

```powershell
python -m flask --app run create-user you@gmail.com --role admin
```

To give a Google admin a password later: `python -m flask --app run rotate-admin-password you@gmail.com` (you are prompted; nothing is read from `.env`).

### Step 10. Run the app

```powershell
python run.py
```

Open <http://127.0.0.1:5000>. Stop with `Ctrl+C`. (Equivalent: `python -m flask --app run run`.)

### Step 11. Run the tests

```powershell
python -m pytest -q
```

See [section 13](#13-testing).

### First-run checklist

- [ ] Python 3.14 installed, `(.venv)` active, `requirements.txt` installed
- [ ] MySQL running; `laundrix_db` and user created (script password changed)
- [ ] `.env` created with `SECRET_KEY`, `DB_USER`, `DB_PASSWORD`
- [ ] `check-db` succeeds; `db upgrade` reaches `a1d5c8e3b7f2`
- [ ] `seed-catalog` and `seed-payments` done
- [ ] Admin created; `INITIAL_ADMIN_PASSWORD` removed from `.env`
- [ ] Home page opens and admin can sign in
- [ ] `pytest` passes

## 6. Environment variables

`config.py` reads everything from `.env`. Required to start: **`SECRET_KEY`, `DB_USER`, `DB_PASSWORD`**. Put comments on their own line in `.env`, and restart the server after any change. The app **refuses to start** on certain half-configured setups (noted below) so mistakes show up immediately.

### App

| Variable | Default | Description |
|---|---|---|
| `APP_ENV` | `development` | `development` or `production`. Production forces secure cookies and HTTPS |
| `SECRET_KEY` | none (**required**) | Signs sessions and CSRF tokens. Unique per environment |
| `APP_BASE_URL` | `http://127.0.0.1:5000` | Public URL used for QR links, OAuth/Didit callbacks, enrollment links. **Must be `https://` in production** |
| `SESSION_LIFETIME_MINUTES` | `480` | Login session length |
| `BEHIND_PROXY` | `false` | `true` on Render/Nginx/Cloudflare so IP and scheme are read from proxy headers |
| `RATELIMIT_STORAGE_URI` | `memory://` | Use `redis://HOST:6379` when running several Gunicorn workers |

### Database

| Variable | Default | Description |
|---|---|---|
| `DB_HOST` | `localhost` | Database host (TiDB Cloud host in production) |
| `DB_PORT` | `3306` | `4000` for TiDB Cloud |
| `DB_NAME` | `laundrix_db` | Database name |
| `DB_USER` / `DB_PASSWORD` | none (**required**) | Database credentials |
| `DB_SSL_CA` | empty | Path to a CA file. **Required for TiDB Cloud**; leave empty for local MySQL |
| `DB_SSL_VERIFY_CERT` | `true` | Verify the server certificate |
| `DB_SSL_VERIFY_IDENTITY` | `true` | Verify the hostname |

### Sign-in

| Variable | Default | Description |
|---|---|---|
| `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` | empty | Google OAuth client. Sign-in with Google fails until set |
| `GOOGLE_ALLOWED_DOMAIN` | empty | Optional: only allow Google accounts from this domain |
| `STAFF_GOOGLE_LOGIN_ALLOWED` | `true` | Let staff use Google (the account must already exist) |
| `ADMIN_PASSWORD_LOGIN_ENABLED` | `true` | Allow admin username/email + password |
| `INITIAL_ADMIN_USERNAME` / `INITIAL_ADMIN_PASSWORD` / `INITIAL_ADMIN_EMAIL` | empty | Read **only** by `bootstrap-admin`. Remove the password afterwards |
| `STAFF_MAX_FAILED_ATTEMPTS` | `5` | Failed staff logins before lockout |
| `STAFF_LOCKOUT_MINUTES` | `15` | Lockout length |
| `STAFF_LOGIN_WINDOW_SECONDS` | `600` | Window in which failures are counted |
| `STAFF_ENROLL_TOKEN_HOURS` | `24` | Lifetime of a single-use staff enrollment link |

### Identity verification and Face Login (Didit)

| Variable | Default | Description |
|---|---|---|
| `IDV_ENABLED` | `false` | Master switch. When `true`, `DIDIT_API_KEY`, `DIDIT_WORKFLOW_ID` and `DIDIT_WEBHOOK_SECRET` are required |
| `IDV_PROVIDER` | `didit` | Only `didit` is supported |
| `DIDIT_API_KEY` | empty | Didit Console, API & Webhooks. Backend only |
| `DIDIT_WORKFLOW_ID` | empty | KYC + Liveness + Face Match workflow |
| `DIDIT_WEBHOOK_SECRET` | empty | Webhook destination secret (shown once) |
| `DIDIT_BIOMETRIC_WORKFLOW_ID` | empty | Biometric Authentication workflow. Needed for staff face sign-in |
| `DIDIT_BASE_URL` | `https://verification.didit.me` | Must be `https://` |
| `DIDIT_ENVIRONMENT` | `sandbox` | `sandbox` or `live`. **Must be `live` in production** (enforced) |
| `DIDIT_SANDBOX_SCENARIO` | empty | Sandbox only. **Must be empty in production** (enforced) |
| `IDV_MAX_ATTEMPTS` / `IDV_ATTEMPT_WINDOW_HOURS` | `3` / `24` | Attempts per user per window |
| `IDV_RETENTION_DAYS` | `365` | Age after which `idv-purge` deletes non-verified records |
| `IDV_POLL_COOLDOWN_SECONDS` | `15` | Minimum gap between status polls |
| `IDV_HTTP_CONNECT_TIMEOUT` / `IDV_HTTP_READ_TIMEOUT` | `3.05` / `10` (code default; `.env.example` uses `10` / `30`) | Timeouts for Didit API calls, in seconds |
| `IDV_PRIVACY_CONTACT_EMAIL` | empty | Shown in the consent notice |
| `IDV_BIOMETRIC_MAX_PER_HOUR` | `6` | Face checks one person may start per hour |
| `IDV_BIOMETRIC_POLL_COOLDOWN_SECONDS` | `3` | Poll gap for face checks |
| `IDV_BIOMETRIC_RETENTION_DAYS` | `90` | Sign-in face-check records are deleted after this |
| `FACE_LOGIN_MIN_SIMILARITY` | `90` (example: `80`) | Face Search score threshold (0-100) |
| `FACE_LOGIN_MIN_MARGIN` | `5` | Best match must beat the next different person by this much |

### SMS (UniSMS)

| Variable | Default | Description |
|---|---|---|
| `SMS_ENABLED` | `false` | With `true`, the app **refuses to start** unless the key is set and the URL is `https://` |
| `UNISMS_API_BASE_URL` | `https://unismsapi.com/api` | Must be `https://` |
| `UNISMS_API_SECRET_KEY` | empty | Basic-auth username (password left empty). Server-side only |
| `UNISMS_SENDER_ID` | `Unisoft` | Sender ID approved on your UniSMS account |
| `SMS_CONNECT_TIMEOUT` / `SMS_READ_TIMEOUT` | `3.05` / `10` | Timeouts in seconds |

### File storage

| Variable | Default | Description |
|---|---|---|
| `PROFILE_AVATAR_DIR` | built-in `instance/` path | Where profile pictures are saved |
| `PAYMENT_UPLOAD_DIR` | built-in `instance/` path | Where the payment QR image is saved |

On Render, point both at a **persistent disk** path, or uploads disappear on each deploy.

## 7. Configure external services

Only configure what you need. The app boots with all of them unset.

### 7.1 Google OAuth

1. Open <https://console.cloud.google.com/apis/credentials> and select (or create) a project.
2. Configure the **OAuth consent screen**. While it is in *Testing* mode, add every Google account that will sign in as a **test user**.
3. **Create credentials, OAuth client ID, Web application**.
4. Under **Authorized redirect URIs** add one URI per environment, exactly (including `http`/`https` and `127.0.0.1` vs `localhost`):
   - Local: `http://127.0.0.1:5000/auth/callback`
   - Production: `https://YOUR-DOMAIN/auth/callback`
5. Copy the client ID and secret into `.env`:

   ```env
   GOOGLE_CLIENT_ID=...
   GOOGLE_CLIENT_SECRET=...
   GOOGLE_ALLOWED_DOMAIN=
   ```
6. Restart the server. Google only signs in accounts that **already exist** in Laundrix (created with `create-user` or by an admin); it never creates accounts on its own.

### 7.2 Didit identity verification and Face Login

Skip this if you do not need ID checks or face sign-in. Full detail: [`docs/identity_verification.md`](docs/identity_verification.md) and [`docs/face_login_guide.md`](docs/face_login_guide.md).

1. Sign up at <https://business.didit.me>. Create **two applications**: a **sandbox** one (development) and a **live** one (production). A key belongs to exactly one application.
2. **Workflows, Create Workflow**: start from the **KYC** template and add **Liveness Detection** and **Face Matching**. Copy the **Workflow ID** into `DIDIT_WORKFLOW_ID`. Review the countries and ID types you accept.
3. **Create a second workflow of type Biometric Authentication** and copy its ID into `DIDIT_BIOMETRIC_WORKFLOW_ID` (required for staff Face Login).
4. **Settings, API & Webhooks**: copy the **API key** into `DIDIT_API_KEY`.
5. Create a **webhook destination**:
   - URL: `https://YOUR-DOMAIN/identity/webhook/didit`
   - Version: `v3`, subscribed event: `status.updated`
   - Copy its **secret** immediately (shown once) into `DIDIT_WEBHOOK_SECRET`.
6. Set the rest in `.env`:

   ```env
   IDV_ENABLED=true
   IDV_PROVIDER=didit
   DIDIT_ENVIRONMENT=sandbox          # live in production
   IDV_PRIVACY_CONTACT_EMAIL=privacy@your-domain
   ```
7. If you sit behind Cloudflare or a WAF, allow Didit's webhook IP (documented as `18.203.201.92`; confirm in Didit's docs).
8. Restart, then open the dashboard and use **Identity verification**.

Important:

- Didit **cannot call `localhost`**. For local webhook testing use an HTTPS tunnel and set `APP_BASE_URL` to it; otherwise rely on the return page and the `idv-reconcile` command.
- A **sandbox** application returns mocked results and can never match a real face. Face Login needs a **live** application with credits.
- Browsers only allow the camera on `https://` or `http://localhost`.
- Staff enrolled under a different Didit application must re-enroll: `python -m flask --app run new-enroll-link staff@example.com`.
- Never use production credentials or real ID documents for ordinary development tests.

### 7.3 UniSMS (SMS notifications)

1. Create a UniSMS account, top up credits, and copy your **API secret key**. Use the Sender ID your account is approved for.
2. Add to `.env`:

   ```env
   SMS_ENABLED=false
   UNISMS_API_BASE_URL=https://unismsapi.com/api
   UNISMS_API_SECRET_KEY=<your secret key>
   UNISMS_SENDER_ID=Unisoft
   SMS_CONNECT_TIMEOUT=3.05
   SMS_READ_TIMEOUT=10
   ```
3. **Test with your own phone first:** set `SMS_ENABLED=true`, restart, create an order with the consent box ticked and *your* number, then move it to **Ready for Pickup**. Keep `SMS_ENABLED=false` until you are happy.
4. Migrations must be applied (`db upgrade`). SMS only works for Philippine mobile numbers (`09171234567`, `+639171234567`, `639171234567`).

### 7.4 TiDB Cloud (production database)

1. Create a TiDB Cloud cluster and a database (for example `laundrix_db`).
2. In the cluster's **Connect** dialog copy the host, port (`4000`), username and password.
3. Download the CA certificate (`isrgrootx1.pem`, ISRG Root X1) and keep it **outside Git** (`*.pem` is gitignored).
4. Set in the production environment:

   ```env
   DB_HOST=<cluster host>
   DB_PORT=4000
   DB_NAME=<database name>
   DB_USER=<tidb user>
   DB_PASSWORD=<tidb password>
   DB_SSL_CA=/etc/secrets/isrgrootx1.pem
   DB_SSL_VERIFY_CERT=true
   DB_SSL_VERIFY_IDENTITY=true
   ```
5. Allow your Render service (and your own IP, if you run migrations from your computer) in the cluster's network access list.

### 7.5 Redis (optional, for rate limiting)

With more than one Gunicorn worker, `memory://` gives each worker its own counter. Provide a Redis URL instead:

```env
RATELIMIT_STORAGE_URI=redis://HOST:6379
```

## 8. First-run data and accounts

| Task | Command |
|---|---|
| Starter catalog | `python -m flask --app run seed-catalog` |
| Payment methods + settings | `python -m flask --app run seed-payments` |
| First admin (password) | `python -m flask --app run bootstrap-admin` |
| Extra admin or staff (Google) | `python -m flask --app run create-user EMAIL --role admin` or `--role staff` |
| Staff with ID verification | `python -m flask --app run create-staff EMAIL --name "Full Name"` (prints a single-use enrollment link) |
| New enrollment link | `python -m flask --app run new-enroll-link EMAIL` |
| Staff status | `python -m flask --app run staff-status EMAIL` |
| Set a staff password | `python -m flask --app run set-staff-password EMAIL` |
| Deactivate staff | `python -m flask --app run deactivate-staff EMAIL` |

After the first admin signs in:

1. **Payments, Payment settings**: enter the GCash display name/number and instructions, and upload your payment QR image. It is stored under `instance/uploads/payment_qr/` (gitignored), or `PAYMENT_UPLOAD_DIR` if set. Back that folder up in production.
2. **Services** (`/admin/services`): review the seeded catalog and prices.
3. **Staff** (`/admin/staff`): create or approve staff.

## 9. Using the app

| Page | URL | Who |
|---|---|---|
| Landing page | `/` | Public |
| Admin sign-in | `/auth/admin` | Admin |
| Staff / admin sign-in | `/auth/login` | Staff, Admin |
| Dashboard | `/dashboard` (staff view `/dashboard/staff`) | Staff, Admin |
| Orders, New Order, Customers | `/orders/`, `/orders/new`, `/orders/customers` | Staff, Admin |
| Outstanding balances | `/payments/outstanding` | Staff, Admin |
| Payment records, summary, settings | `/payments/`, `/payments/summary`, `/payments/settings` | Admin |
| Service catalog | `/admin/services` | Admin |
| Staff management | `/admin/staff` | Admin |
| Audit logs | `/admin/audit-logs` | Admin |
| Analytics & Reports | `/admin/analytics` | Admin |
| Identity verification | `/identity/` | Signed-in users (when enabled) |
| Public order tracking | `/track/<token>` | Customer (via QR) |

### Order and payment workflow

1. Staff creates an order in the **New Order** wizard. The server validates amounts against its own total; going back creates nothing, and the order is only saved on **Confirm and generate stub**.
2. Print the stub (browser print) and press **Laundry received**. *Order received* and *payment received* are separate events.
3. Later balances are recorded from the order page. `payments` is an append-only ledger; status (Unpaid / Partially Paid / Paid) is derived from it. Overpayment is rejected, and corrections are admin-only **reversals** with a reason.
4. Moving an order to **Ready for Pickup** can send one SMS (see below).

### SMS rules

- One message per order, the first time it reaches **Ready for Pickup**, and only if the customer consented **on that order**.
- It is sent only after the status change is committed, so an SMS outage never blocks a status change. Nothing is retried automatically.
- Statuses shown to staff: Pending, Queued/Retrying, Sent by provider, Failed (staff may **Retry SMS**), Outcome unknown (never auto-retried; check the UniSMS dashboard first), Skipped.

| Symptom | Likely cause |
|---|---|
| Failed: authentication failed | Wrong or revoked `UNISMS_API_SECRET_KEY` (restart after editing) |
| Failed: insufficient credits | Top up UniSMS, then **Retry SMS** |
| Failed: rejected the request | Invalid number, or Sender ID not allowed on that network |
| Pending, nothing happens | `SMS_ENABLED` is false; enable it, then press **Send SMS** |
| Skipped: invalid number | Saved contact is not a Philippine mobile number |

### QR tracking links

The QR code is built from `APP_BASE_URL`. A QR containing `127.0.0.1` only opens on the same computer. To test scanning from a phone, temporarily set `APP_BASE_URL` to an HTTPS tunnel URL, restart, and generate a **new** stub (old QR codes keep their old URL). Never commit a tunnel URL.

## 10. Analytics and the unclaimed-order model

The admin-only page at `/admin/analytics` shows 7/30/90-day charts (orders, revenue, status mix, popular services), a CSV export, and one model that scores every order waiting for pickup with a **disposal-risk** score.

- **Training data comes from Laundrix itself.** An order is a training example only when its outcome is confirmed: it was **picked up** (status history), or an admin pressed **Mark disposed** on the Analytics page. It must also be *mature* (ready at least 30 days ago).
- **Inputs:** order total, paid by the time it became ready, number of the customer's earlier orders, ready on a weekend. Names, phone numbers, IDs and Didit data are never inputs.
- **Readiness rules** (`app/analytics/ml/policy.py`): at least 100 confirmed orders, at least 10 picked up and 10 disposed, and ROC-AUC of at least 0.60 on the newest orders. Until then the page shows progress and **no scores**.
- **Storage:** the model's parameters are stored in the database, so it survives Render redeploys.

Commands:

```powershell
python -m flask --app run analytics train                       # train now, if there is enough data
python -m flask --app run analytics import-history --file PATH  # legacy CSV import, dry-run by default (add --execute to write)
python -m flask --app run analytics purge-simulated             # counts simulated rows; add --execute to delete them
```

The history CSV (`washup_laundry_shop_history.csv`) contains customer first names, so it is gitignored. Keep it outside the repository. See [`docs/ANALYTICS_SYSTEM_ML_GUIDE.md`](docs/ANALYTICS_SYSTEM_ML_GUIDE.md).

## 11. Frontend (React) bundles

The React pages (orders, dashboard, catalog, staff) are built into `app/core/static/react*/` and **those built files are committed**, so you do **not** need Node.js to run or deploy Laundrix. You only need Node if you edit `frontend/src`.

```powershell
cd frontend
npm ci                     # install exact dependencies from package-lock.json
npm run build              # orders bundle  -> app/core/static/react
npm run build:dashboard    # dashboard      -> app/core/static/react-dashboard
npm run build:catalog      # catalog        -> app/core/static/react-catalog
npm run build:staff        # staff          -> app/core/static/react-staff
npm run lint               # oxlint
```

Rebuild the bundle you changed and commit the updated files under `app/core/static/`. `npm run test:e2e` and the other `test:*` scripts run Playwright browser tests (optional; they use an isolated test server, not your real database).

## 12. CLI command reference

Run everything from the project root with the virtual environment active. Prefix: `python -m flask --app run`.

| Command | Purpose |
|---|---|
| `check-db` | Test the database connection |
| `db heads` / `db current` / `db upgrade` / `db downgrade REV` | Alembic migrations |
| `seed-catalog` | Insert the starter service catalog (idempotent) |
| `seed-payments` | Insert Cash/GCash and the settings row (idempotent) |
| `bootstrap-admin [--allow-additional]` | Create the first admin from `INITIAL_ADMIN_*` |
| `rotate-admin-password [EMAIL_OR_USERNAME]` | Set/change an admin password (prompted) |
| `create-user EMAIL --role admin\|staff [--name N]` | Pre-authorize a Google account |
| `create-staff EMAIL [--name N]` | Create staff and print a single-use enrollment link |
| `new-enroll-link EMAIL` | New enrollment link (re-verification) |
| `staff-status EMAIL` | Verified / locked / link pending |
| `set-staff-password EMAIL` | Set a staff password |
| `deactivate-staff EMAIL` | Deactivate a staff account |
| `idv-status EMAIL` | A user's verification attempts |
| `idv-reconcile [--older-than-minutes N]` | Poll Didit for missed webhooks |
| `idv-purge [--days N] [--dry-run]` | Delete verification records past retention |
| `analytics train` | Train the unclaimed-order model |
| `analytics import-history --file F [--source S] [--execute]` | Validate/import legacy history CSV |
| `analytics purge-simulated [--execute]` | Remove simulated history rows |

`python -m flask --app run --help` lists everything.

## 13. Testing

```powershell
python -m pytest -q                              # full default suite (in-memory SQLite, no real services)
python -m pytest -q tests/test_smoke.py          # one file
python -m pytest -q tests/analytics tests/laundry/test_analytics_system.py
```

`pytest.ini` skips tests marked `integration` (they call the real Didit sandbox and need `DIDIT_SANDBOX_API_KEY` and `DIDIT_SANDBOX_WORKFLOW_ID`). The test configuration never contacts SMS or your real database, whatever your `.env` says. If a test fails, read it and fix the cause; do not commit around it.

## 14. Deploying to Render + TiDB Cloud

Laundrix runs on **Render** (web service) with **TiDB Cloud** as the database.

### 14.1 Before the first deploy

1. Create the TiDB cluster and gather its connection details ([7.4](#74-tidb-cloud-production-database)).
2. Push the code to GitHub (never `.env`).
3. In Google Cloud add `https://YOUR-DOMAIN/auth/callback` as an authorized redirect URI.
4. If you use Didit, create the **live** application and webhook pointing at `https://YOUR-DOMAIN/identity/webhook/didit`.

### 14.2 Create the Render web service

1. Render dashboard, **New, Web Service**, connect the GitHub repository.
2. Settings:

   | Setting | Value |
   |---|---|
   | Runtime | Python (version from `.python-version`) |
   | Build Command | `pip install -r requirements.txt` |
   | Start Command | `gunicorn run:app` |
   | Health check path | `/` |

3. **Secret File:** add `isrgrootx1.pem`; Render mounts it at `/etc/secrets/isrgrootx1.pem`.
4. **Disk (recommended):** attach a persistent disk and set `PROFILE_AVATAR_DIR` / `PAYMENT_UPLOAD_DIR` to paths on it.
5. **Environment variables** (Render, Environment). Never put these in Git:

   ```env
   APP_ENV=production
   SECRET_KEY=<new random 64-hex value, different from local>
   APP_BASE_URL=https://YOUR-DOMAIN
   BEHIND_PROXY=true
   SESSION_LIFETIME_MINUTES=480
   RATELIMIT_STORAGE_URI=memory://        # or a redis:// URL

   DB_HOST=<tidb host>
   DB_PORT=4000
   DB_NAME=<database>
   DB_USER=<user>
   DB_PASSWORD=<password>
   DB_SSL_CA=/etc/secrets/isrgrootx1.pem
   DB_SSL_VERIFY_CERT=true
   DB_SSL_VERIFY_IDENTITY=true

   GOOGLE_CLIENT_ID=...
   GOOGLE_CLIENT_SECRET=...
   ADMIN_PASSWORD_LOGIN_ENABLED=true
   STAFF_GOOGLE_LOGIN_ALLOWED=true

   # Only if used:
   IDV_ENABLED=true
   DIDIT_ENVIRONMENT=live
   DIDIT_API_KEY=...
   DIDIT_WORKFLOW_ID=...
   DIDIT_BIOMETRIC_WORKFLOW_ID=...
   DIDIT_WEBHOOK_SECRET=...
   IDV_PRIVACY_CONTACT_EMAIL=...
   SMS_ENABLED=true
   UNISMS_API_SECRET_KEY=...
   ```

   The production config **refuses to boot** if `APP_BASE_URL` is not `https://`, if `IDV_ENABLED=true` with `DIDIT_ENVIRONMENT` other than `live`, or if `DIDIT_SANDBOX_SCENARIO` is set.

### 14.3 Run database migrations

Run migrations **before** the new code goes live, whenever a release contains a new migration:

```powershell
# From your computer, with a temporary .env pointing at TiDB (then restore your local .env):
python -m flask --app run check-db
python -m flask --app run db current
python -m flask --app run db upgrade
```

or run the same `db upgrade` command in the service's Render **Shell** (available on paid instances). Take a TiDB backup first.

### 14.4 First production data

In the Render Shell (or from your computer against TiDB):

```bash
python -m flask --app run seed-catalog
python -m flask --app run seed-payments
python -m flask --app run bootstrap-admin   # needs INITIAL_ADMIN_* set temporarily; remove the password afterwards
```

### 14.5 Release routine

1. `python -m pytest -q` passes locally.
2. Back up the TiDB database.
3. If there is a new migration: `db heads` shows one head, then `db upgrade` against TiDB.
4. `git push` to the deployed branch; Render redeploys.
5. Smoke test: landing page, admin sign-in, dashboard, one order, a `/track/<token>` link.

## 15. Operations and maintenance

- **Backups:** export TiDB regularly and before every migration. Back up the upload folders. Keep dumps out of Git (`*.sql`, `database_backups/` are gitignored).
- **Scheduled jobs** (Render Cron Job or any scheduler), if identity verification is on:
  - `python -m flask --app run idv-reconcile` about every 10 minutes
  - `python -m flask --app run idv-purge` periodically (respects `IDV_RETENTION_DAYS`)
- **Logs:** in production the app logs to stdout (visible in Render Logs). Face Login logs one diagnostic line per candidate, used to calibrate `FACE_LOGIN_MIN_SIMILARITY`.
- **Rotating secrets:** change the value in Render's environment, then redeploy. Changing `SECRET_KEY` signs everyone out.
- **Rolling back the identity tables only:** `db downgrade 4b1d2288b22d` drops the verification tables permanently. Back up first, or set `IDV_ENABLED=false` to disable the feature without touching data.

## 16. Security notes

- Secrets live only in `.env` (local) or Render's environment (production). `.env*`, `*.pem`, `*.key`, `*.sql`, `*.csv`, `database_backups/`, `instance/`, `uploads/` and `logs/` are gitignored.
- If a secret is ever committed, deleting it in a later commit is **not enough**: revoke/rotate it and tell the repository owner.
- Production forces HTTPS, secure and HttpOnly cookies, and a strict Content-Security-Policy (no inline scripts; the camera is allowed only for the app itself).
- Do not add `form-action 'self'` to the CSP; it would block the redirect to Didit.
- Identity images never touch Laundrix: Didit's hosted page handles them, and results are trusted only from the signed webhook or a server-side API call.
- Customers can see only their own order's status and balance, through an unguessable tracking token.
- The model uses no personal identifiers, and analytics exports exclude customer phone numbers.

## 17. Troubleshooting

| Problem | Fix |
|---|---|
| `python` is not recognized | Reinstall Python with *Add to PATH*, reopen the terminal |
| PowerShell blocks `Activate.ps1` | `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass`, then activate again |
| `ModuleNotFoundError` | Activate `(.venv)` and run `python -m pip install -r requirements.txt` |
| `Missing required environment variables` | `.env` must exist in the project root with `SECRET_KEY`, `DB_USER`, `DB_PASSWORD` |
| Database connection fails | Check MySQL is running and the `DB_*` values; the user needs privileges on `laundrix_db`. For TiDB check `DB_PORT=4000`, `DB_SSL_CA` path and the network access list |
| `redirect_uri_mismatch` (Google) | The URI in Google Cloud must exactly equal `<APP_BASE_URL>/auth/callback`; `localhost` and `127.0.0.1` differ |
| Google sign-in says access denied | Add the account as a test user, and make sure it exists in Laundrix (`create-user`) |
| App won't start: `APP_BASE_URL must be an https:// URL` | Production needs an `https://` base URL |
| App won't start: `DIDIT_ENVIRONMENT must be 'live'` | Set `live` in production, or turn `IDV_ENABLED` off |
| App won't start: `SMS_ENABLED=true but UNISMS_API_SECRET_KEY is not set` | Set the key, or set `SMS_ENABLED=false` |
| Face Login unavailable (404) | `IDV_ENABLED=false` |
| Face Login "temporarily unavailable" (503) | Didit key, credits or rate limit; check the server log |
| Face Login "couldn't recognise your face" (401) | Liveness failed, score under threshold, tie, not Approved, or not active staff. Read the diagnostic log; see `docs/face_login_guide.md` |
| Camera button disabled | Needs `https://` or `http://localhost`, and browser camera permission |
| Two migration heads | Stop. Do not edit history; ask the team. A merge revision (`db merge`) may be needed |
| Migration errors | Check `db current` and `db heads`; share the full error. Never edit `alembic_version` |
| Uploads vanish after deploy | Use a Render persistent disk and set `PROFILE_AVATAR_DIR` / `PAYMENT_UPLOAD_DIR` |
| Analytics shows "not ready" | Not enough confirmed orders yet (needs 100, with 10 picked up and 10 disposed) |

## 18. Git workflow

```powershell
git switch main
git pull
git switch -c feature/short-description

# ...make changes...
git status
git diff --check
python -m pytest -q
git add .
git diff --cached          # review: no secrets, no .env, no dumps
git commit -m "Describe the change"
git push -u origin feature/short-description
```

Open a Pull Request, have it reviewed, then merge. Do not commit `.env`, `.venv/`, `__pycache__/`, `instance/`, logs, database dumps, CSV data, tunnel URLs, or personal machine settings.

## 19. Further documentation

| File | Topic |
|---|---|
| [`docs/identity_verification.md`](docs/identity_verification.md) | Didit identity verification: how it works, setup, statuses, operations |
| [`docs/face_login_guide.md`](docs/face_login_guide.md) | Staff Face Login: prerequisites, calibration, troubleshooting |
| [`docs/ANALYTICS_SYSTEM_ML_GUIDE.md`](docs/ANALYTICS_SYSTEM_ML_GUIDE.md) | Analytics page, model rules, CSV export |
| [`docs/UNCLAIMED_ORDER_ML_GUIDE.md`](docs/UNCLAIMED_ORDER_ML_GUIDE.md) | Earlier implementation guide for the unclaimed-order model |
| [`docs/DATABASE_SCHEMA.md`](docs/DATABASE_SCHEMA.md) | Database tables |
| [`docs/audit_logs.md`](docs/audit_logs.md) | Audit log events and access |
