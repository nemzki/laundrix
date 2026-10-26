# Laundrix

Laundry business management — Flask + MySQL, Google sign-in, admin/staff roles.

## Setup
1. `python -m venv venv` then activate it; `pip install -r requirements.txt`
2. In MySQL Workbench run `scripts/create_database.sql`
3. `cp .env.example .env` and fill in the values (never commit `.env`)
4. `flask --app run check-db`
5. `flask --app run db init` → `flask --app run db migrate -m "users"` → `flask --app run db upgrade`
6. `flask --app run create-user you@gmail.com --role admin`
7. `flask --app run run --debug`  → http://127.0.0.1:5000

## Google OAuth
Google Cloud Console → APIs & Services → Credentials → OAuth client ID (Web application).
Authorized redirect URI: `http://127.0.0.1:5000/auth/callback` (add your https domain for production).

## Structure
Each feature is a blueprint package with its own `templates/<feature>/` and `static/`.
Shared layout/CSS/errors/decorators live in `app/core`.

## Identity verification (government ID + liveness + face match)

Optional feature, **off by default** (`IDV_ENABLED=false`). Users are sent to a hosted verification
page run by Didit; Laundrix stores only the result and an audit trail, never ID images, selfies or
ID numbers. Full setup, privacy notes, testing and rollback: [`docs/identity_verification.md`](docs/identity_verification.md).

```
flask --app run db upgrade        # creates identity_verifications + identity_verification_events
flask --app run idv-status you@example.com
```

## Staff portal (email → Staff ID → live selfie)

Staff sign in at `/staff/login` in three pages: email, Staff ID, then a quick live selfie that Didit
(Biometric Authentication) compares with the portrait it stored when the person first verified their ID.
Laundrix stores no face data, only a hashed Staff ID and sign-in records. Setup: `docs/identity_verification.md`
(sections 3.3 to 3.5, including moving off the old AWS Rekognition system).

```
flask --app run create-staff sam@example.com --name "Sam Cruz"   # Staff ID + one-time onboarding link
flask --app run new-enroll-link sam@example.com                  # re-verify / migrate from AWS
```
The portal stays **unavailable** until `IDV_ENABLED=true` and `DIDIT_BIOMETRIC_WORKFLOW_ID` are set.
