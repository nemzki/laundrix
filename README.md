# Laundrix

Laundrix is a laundry business management system built with **Python, Flask, and MySQL**. The repository contains the Flask application, database migrations, authentication and identity-verification integrations, service catalog, customer/order workflows, QR-based public order tracking, and automated tests.

This guide is for the three-person development team. Each developer runs their own local copy of Laundrix and their own development database. GitHub is used to share source code; it does not share a developer's `.env`, database, OAuth credentials, Didit credentials, or running server.

> **Important:** Do not commit `.env`, API keys, OAuth client secrets, database passwords, real customer data, or identity-verification data.

---

## 1. Requirements

Install the following on each developer's Windows computer:

| Requirement | Purpose | Where to get it |
|---|---|---|
| Git | Clone, pull, branch, and push code | https://git-scm.com/downloads |
| Python | Run the Flask application | https://www.python.org/downloads/ |
| MySQL Server | Store application data locally | https://dev.mysql.com/downloads/mysql/ |
| MySQL Workbench | Create/manage the local database (optional but recommended) | https://dev.mysql.com/downloads/workbench/ |
| A code editor | Edit the project (PyCharm recommended by the project owner) | https://www.jetbrains.com/pycharm/ |

Use a currently supported Python 3 version compatible with the packages in `requirements.txt`. During installation, enable **Add Python to PATH** if the installer offers that option.

Check installations in PowerShell:

```powershell
git --version
python --version
python -m pip --version
```

Check that the MySQL server is running before continuing.

---

## 2. Clone the repository

Open PowerShell in the folder where you keep your projects:

```powershell
git clone YOUR_GITHUB_REPOSITORY_URL
cd laundrix
```

Replace `YOUR_GITHUB_REPOSITORY_URL` with the repository's actual HTTPS or SSH clone URL.

If you already cloned the project, update your local copy from the appropriate team branch:

```powershell
git switch develop
git pull
```

If the team has not created a `develop` branch, use the branch agreed upon by the repository owner. Do not assume that `main` and `develop` are interchangeable.

---

## 3. Create and activate a virtual environment

Run these commands from the project root (the folder containing `requirements.txt`):

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

If PowerShell blocks activation, run this command for the current PowerShell process only, then activate again:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
```

The terminal should show `(.venv)` when the environment is active.

Upgrade pip and install the project's Python dependencies:

```powershell
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

The dependencies include Flask and its extensions, SQLAlchemy and Flask-Migrate/Alembic, MySQL's PyMySQL driver, Authlib for Google OAuth, requests for provider API calls, python-dotenv, qrcode with Pillow, Gunicorn for Linux deployment, and pytest for tests.

Whenever `requirements.txt` changes, pull the latest code and run:

```powershell
python -m pip install -r requirements.txt
```

---

## 4. Create a local MySQL database

Each developer should use a separate local development database. Do not point all developers at one shared development database unless the team deliberately sets up and manages a shared database server.

1. Start MySQL Server.
2. Open MySQL Workbench and connect to your local MySQL server.
3. Open `scripts/create_database.sql`.
4. Review the script before executing it. In particular, replace the example database-user password in that SQL file with a strong, unique password of your own. Do not reuse a password from a script or commit your password.
5. Execute the script using a MySQL account with permission to create databases and users.

The script creates the `laundrix_db` database and a local `laundrix_user` account. If you prefer to create the database and user manually, the application database must use `utf8mb4`.

The default database settings expected by the application are:

- Host: `localhost`
- Port: `3306`
- Database: `laundrix_db`

Use the database username and password you configured on your own computer in the next step.

---

## 5. Configure your local environment (`.env`)

Create your own `.env` file by copying the example:

```powershell
Copy-Item .env.example .env
```

Open `.env` and fill in the values for your computer. **Never commit this file.**

At minimum, configure:

```env
APP_ENV=development
SECRET_KEY=PASTE_A_UNIQUE_RANDOM_SECRET_HERE
APP_BASE_URL=http://127.0.0.1:5000
BEHIND_PROXY=false

DB_HOST=localhost
DB_PORT=3306
DB_NAME=laundrix_db
DB_USER=laundrix_user
DB_PASSWORD=YOUR_LOCAL_MYSQL_PASSWORD
```

Generate a unique secret key in PowerShell:

```powershell
python -c "import secrets; print(secrets.token_hex(32))"
```

Copy the generated value into `SECRET_KEY`. Each developer should generate their own value.

### Optional integrations

The app can start with Google OAuth credentials unset, but Google sign-in will not work until a valid OAuth client is configured. Identity verification is disabled by default. Features that depend on Didit will not work until the relevant Didit settings are configured.

#### Google OAuth (for developers who need to test Google sign-in)

1. Create or use a Google Cloud project.
2. Configure the OAuth consent screen as required by Google.
3. Create an OAuth client with application type **Web application**.
4. Add this local development redirect URI to **Authorized redirect URIs**:

   ```text
   http://127.0.0.1:5000/auth/callback
   ```

5. Put the OAuth client values in your local `.env`:

   ```env
   GOOGLE_CLIENT_ID=YOUR_GOOGLE_CLIENT_ID
   GOOGLE_CLIENT_SECRET=YOUR_GOOGLE_CLIENT_SECRET
   GOOGLE_ALLOWED_DOMAIN=
   ```

Do not put OAuth secrets in GitHub. If the team uses one shared OAuth client, share its credentials through a secure secret-sharing method, not a commit, issue, or chat message in the repository. Google OAuth providers may require the developer's test account to be added as an authorized test user while the consent screen is in testing mode.

#### Didit identity verification (optional for local development)

Identity verification is disabled by default:

```env
IDV_ENABLED=false
```

To test the Didit integration, each developer who needs it must obtain the team's approved sandbox configuration and set the relevant values in their own `.env`:

```env
IDV_ENABLED=true
IDV_PROVIDER=didit
DIDIT_API_KEY=YOUR_DIDIT_SANDBOX_API_KEY
DIDIT_WORKFLOW_ID=YOUR_DIDIT_SANDBOX_WORKFLOW_ID
DIDIT_WEBHOOK_SECRET=YOUR_DIDIT_WEBHOOK_SECRET
DIDIT_ENVIRONMENT=sandbox
DIDIT_BASE_URL=https://verification.didit.me
```

The webhook secret is needed when validating Didit webhook events. A provider webhook cannot call a developer's `localhost` address directly; use an approved HTTPS development tunnel or test the relevant flow using the project's supported return/polling behavior. Never use production credentials or real identity documents for ordinary development tests.

The current `.env.example` also includes staff-portal and biometric-workflow settings. Configure those only if you are testing the staff enrollment/sign-in flow implemented by the current branch. Follow [`docs/identity_verification.md`](docs/identity_verification.md) and confirm the current staff authentication flow with the team before enabling it.

---

## 6. Verify the database connection and apply migrations

Make sure:

- Your virtual environment is active.
- MySQL Server is running.
- Your `.env` database values are correct.
- You are in the project root.

Test the connection:

```powershell
python -m flask --app run check-db
```

Check the migration heads:

```powershell
python -m flask --app run db heads
```

The current migration chain should have one head:

```text
fbc865bc8499
```

Apply all migrations to your local database:

```powershell
python -m flask --app run db upgrade
```

Check the current database revision:

```powershell
python -m flask --app run db current
```

Do not run `flask db init` on an existing project. The repository already contains its migration environment and revision history. Do not delete migration files or manually edit the `alembic_version` table to resolve migration errors. Ask the team to review migration conflicts first.

---

## 7. Seed the service catalog

After the database migrations have completed, populate the initial service catalog:

```powershell
python -m flask --app run seed-catalog
```

The seed command is designed to be idempotent and does not overwrite existing catalog rows.

---

## 8. Create a local administrator account

The application provides a CLI command to pre-authorize an administrator's Google account:

```powershell
python -m flask --app run create-user YOUR_GOOGLE_EMAIL --role admin
```

Replace `YOUR_GOOGLE_EMAIL` with the Google account that will be used to sign in. This creates the application user record; it does not create a Google account or configure OAuth for you.

To see the available CLI commands:

```powershell
python -m flask --app run --help
```

Staff account commands are documented in the CLI help and in the identity-verification guide. Use the workflow implemented by the current branch.

---

## 9. Run Laundrix locally

Start the Flask development server:

```powershell
python run.py
```

Open:

```text
http://127.0.0.1:5000
```

Keep the terminal open while using the application. Press `Ctrl+C` to stop the local server.

Each developer runs their own local instance. A collaborator does not need your Cloudflare Tunnel URL or your computer's IP address to run the application locally.

### QR order tracking during local development

The QR code uses `APP_BASE_URL` to build its public tracking link. For ordinary local testing, the default is:

```env
APP_BASE_URL=http://127.0.0.1:5000
```

A QR code containing `127.0.0.1` or `localhost` will only open on the same computer, not on a customer's phone. To test scanning from a phone, that developer must temporarily use an HTTPS tunnel and set `APP_BASE_URL` to that tunnel's current URL, then restart Flask and generate a new order stub/QR code. Quick Tunnel URLs change when restarted, so old QR codes keep their old URL.

Do not commit a tunnel URL to `.env.example` or the repository. A permanent shared QR URL should be configured when the team deploys the application behind a stable domain.

---

## 10. Run the automated tests

Run the full default test suite from the project root:

```powershell
python -m pytest -q
```

The `pytest.ini` configuration excludes tests marked `integration` by default. Integration tests that contact the real Didit sandbox require the appropriate sandbox credentials and should only be run intentionally.

Run a specific test file when debugging:

```powershell
python -m pytest -q tests/test_smoke.py
```

If a test fails, do not ignore it or commit around it. Read the failure, reproduce it, and coordinate with the developer responsible for the affected feature.

---

## 11. Team Git workflow

To reduce conflicts, each developer should work on a separate feature branch.

Example:

```powershell
git switch develop
git pull
git switch -c feature/short-description
```

After making changes:

```powershell
git status
git diff --check
python -m pytest -q
git add .
git diff --cached
git commit -m "Add short description of change"
git push -u origin feature/short-description
```

Open a Pull Request into the team's integration branch (for example, `develop`). Ask another team member to review it before merging. Merge into `main` only when the team considers the release stable.

Before starting new work, update your local integration branch:

```powershell
git switch develop
git pull
```

Do not commit:

- `.env` or any secret values
- `.venv/`, `__pycache__/`, `.pytest_cache/`, or generated logs
- Local database files, database dumps, or real customer records
- Temporary tunnel URLs or personal machine-specific configuration

If a secret is accidentally committed, removing it in a later commit is not enough. Revoke/rotate the exposed credential and notify the repository owner.

---

## 12. Troubleshooting

### `python` is not recognized

Reinstall Python or correct your PATH. Close and reopen PowerShell, then check:

```powershell
python --version
```

### PowerShell says script execution is disabled

Run the process-scoped execution-policy command in section 3, then activate `.venv` again.

### `ModuleNotFoundError`

Confirm that `(.venv)` is active and install dependencies again:

```powershell
python -m pip install -r requirements.txt
```

### MySQL connection fails

Check that MySQL Server is running and verify `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`, and `DB_PASSWORD` in your local `.env`. Confirm that the database user has privileges on `laundrix_db`.

### `SECRET_KEY` or database environment values are missing

Make sure `.env` exists in the project root and contains `SECRET_KEY`, `DB_USER`, and `DB_PASSWORD`. Do not rename `.env.example` instead of copying it; keep the example file in the repository.

### Google OAuth `redirect_uri_mismatch`

The redirect URI in Google Cloud Console must exactly match:

```text
http://127.0.0.1:5000/auth/callback
```

Use the same host consistently. `localhost` and `127.0.0.1` are different redirect URIs.

### Didit is unavailable or verification cannot start

Check `IDV_ENABLED`, the Didit API key, workflow ID, webhook secret, environment (`sandbox` for development), and the configured workflow. Consult [`docs/identity_verification.md`](docs/identity_verification.md).

### Migration errors

Check `python -m flask --app run db current` and `python -m flask --app run db heads`. Do not create a new migration or change the migration history just to bypass an error. Share the complete error with the team.

---

## 13. Project structure

```text
laundrix/
├── app/
│   ├── auth/
│   ├── catalog/
│   ├── core/
│   ├── dashboard/
│   ├── identity/
│   ├── landing/
│   ├── models/
│   ├── orders/
│   ├── staff_auth/
│   └── tracking/
├── docs/
├── migrations/
│   └── versions/
├── scripts/
├── tests/
├── .env.example
├── .gitignore
├── config.py
├── requirements.txt
├── run.py
└── README.md
```

- `app/` — Flask application package, feature blueprints, templates, and static assets.
- `app/models/` — SQLAlchemy models.
- `app/catalog/` — service, package, and add-on catalog management.
- `app/orders/` — customer/order workflows, pricing, and printable order stubs.
- `app/tracking/` — public QR-based order tracking page.
- `app/identity/` — Didit identity-verification integration.
- `app/staff_auth/` — staff authentication and account-management workflows.
- `migrations/` — Alembic/Flask-Migrate database revision history.
- `scripts/` — SQL and development scripts.
- `docs/` — technical documentation.
- `tests/` — automated tests.

---

## 14. Current implementation notes

The repository currently includes:

- Admin and staff authentication/authorization features.
- Google OAuth integration.
- Didit-hosted identity-verification integration (requires configuration and provider testing).
- Admin service catalog management for services, packages, and add-ons.
- Customer and order recording workflows.
- Order pricing and item snapshots.
- Order status changes and status history.
- Printable order stubs with locally generated QR codes.
- A public tracking page accessed through a unique, unguessable tracking token.
- Dashboard summaries based on order data.
- Automated tests.

Check the actual routes, tests, and current branch before assuming a feature is complete. Payments, notifications, inventory, and broader financial reporting should not be considered implemented unless they have been added and tested in a later branch.

---

## 15. First-run checklist

Use this checklist on every new developer machine:

- [ ] Git installed and repository cloned.
- [ ] Python installed and version checked.
- [ ] MySQL Server installed and running.
- [ ] Local `laundrix_db` database and user created.
- [ ] `.venv` created and activated.
- [ ] `requirements.txt` installed successfully.
- [ ] Local `.env` created from `.env.example`.
- [ ] Unique `SECRET_KEY` and local MySQL credentials configured.
- [ ] `check-db` succeeds.
- [ ] Database migrations upgraded to the current head.
- [ ] Catalog seed command completed.
- [ ] Local admin user pre-authorized.
- [ ] Flask server starts and the home page opens.
- [ ] Automated tests pass.
- [ ] Optional Google OAuth / Didit integrations configured only if needed.

If any step fails, record the exact command and full error message and share it with the team. Do not share passwords, API keys, OAuth secrets, or personal identity documents.
