# Identity verification (ID + liveness + face match) and staff face sign-in

Status: implemented against Didit's documented API. **Not yet run against the real Didit sandbox**
(see "What has and hasn't been tested"). Didit also replaces the former AWS Rekognition face login:
see sections 3.3 to 3.5.

## 1. Provider choice

Researched from each vendor's own pricing/docs pages (links at the bottom). Several claims below are
the vendors' own statements; verify them against your account before relying on them.

| | Didit (chosen) | Persona | Sumsub | Veriff |
|---|---|---|---|---|
| Free sandbox | Yes (a per-application *mode*) | Yes | Yes, but runs no real approval logic | Yes |
| Free **real** checks | 500/month, ongoing, no card, includes ID + passive liveness + face match | Startup Program (apply; up to 12 months, 500/month) | 14-day trial, 50 checks, billing details required | 15-day trial, up to 50 sessions, company verification required |
| After free | ~$0.33 full KYC, no minimum | Essential from $250/mo, annual contract | roughly $1.35+/check (third-party figure) | $49/mo minimum + $0.80/check (third-party figure) |
| Hosted flow (images never touch your server) | Yes | Yes | Yes (WebSDK / links) | Yes |
| Webhook auth | HMAC-SHA256 (V2) + `event_id` | HMAC (`Persona-Signature`) | HMAC | HMAC |
| Philippine IDs | Provider lists Passport, UMID, Driver's License, SSS, PRC, PhilHealth, Postal, OFW, NBI, PhilSys and more | API lists PH classes (UMID, SSS, Postal, NBI, OFW) plus generic DL/passport/ID; PhilSys not confirmed | not confirmed in my research | not confirmed in my research |

**Why Didit:** it is the only candidate where real (not mocked) end-to-end checks are free on an
ongoing basis with no minimum, which suits a small business and lets you test with real documents.

**Risks to weigh:** Didit is a young company (seed-stage), so the code keeps the provider behind an
interface (`app/identity/provider/base.py`) to make a later swap realistic. Its sandbox returns
*mocked* results, so it cannot tell you whether a real Philippine ID is read correctly. The Philippine
document list comes from Didit's marketing page, not from a per-document guarantee.

**Test every ID type you intend to accept** with a real document on the free live tier before
relying on it. Do not assume every Philippine ID works.

## 2. How it works

```
 User ──(1) consent + POST /identity/start──────────────► Laundrix
 Laundrix ──(2) POST /v3/session/ (x-api-key, vendor_data="laundrix:<user_id>")──► Didit
 Laundrix ◄──(3) {session_id, url=https://verify.didit.me/...} ──── Didit
 User ──(4) 302 redirect to hosted page: ID photo, liveness selfie, face match──► Didit
 Didit ──(5a) POST /identity/webhook/didit  (signed)  ─────────► Laundrix  → status updated
 User ◄──(5b) redirect to /identity/return ◄──── Didit            Laundrix polls GET /v3/session/{id}/decision/
```

* The result is trusted only from (5a) the **HMAC-signed webhook** or (5b) a **server-side API call**.
  The query string Didit appends to the return URL is user-controllable and is ignored.
* A hosted redirect (not an iframe) is used, so your CSP needs no changes. Do **not** add
  `form-action 'self'` to the CSP: it would block the redirect to Didit after the Start form.

### Statuses

| App status | Meaning | Comes from Didit |
|---|---|---|
| `not_started` | no attempt (derived) | – |
| `in_progress` | session created | Not Started, In Progress, Awaiting User |
| `pending_review` | human review | In Review |
| `action_required` | user must restart/resubmit | Resubmitted, Abandoned, Expired, Kyc Expired |
| `verified` | approved | Approved |
| `rejected` | a real verification failure | Declined |
| `error` | **our/provider API failed; not a verdict on the user** | (timeouts, 403, 429, 5xx on our calls only) |

Allowed moves are defined in `app/identity/statuses.py` (`ALLOWED_TRANSITIONS`): `rejected` is final
(retry = a new attempt); `verified` can only move to `action_required` (approval expiry).
A timeout never produces `rejected`.

## 3. Setup

### 3.1 Didit
1. Sign up at business.didit.me. Create **two applications**: one in **sandbox** mode (for development),
   one **live** (for production). A key belongs to exactly one application.
2. *Workflows → Create Workflow →* start from the **KYC** template and add **Liveness Detection** and
   **Face Matching**. Copy the **Workflow ID**. (Country/document options live in the workflow; review
   them for the Philippine IDs you accept.)
3. *Settings → API & Webhooks:* copy the **API key**.
4. Create a **webhook destination**: URL `https://<your-domain>/identity/webhook/didit`, version `v3`,
   subscribed events `["status.updated"]`. Copy its **secret** (shown only once).
5. If your site is behind Cloudflare/a WAF, allow Didit's webhook IP (documented as `18.203.201.92`).
   Didit cannot deliver to localhost; for local work use a tunnel, or rely on the return-page/refresh
   polling described below.

### 3.2 Laundrix
```
# .env  (never commit)
IDV_ENABLED=true
DIDIT_API_KEY=...
DIDIT_WORKFLOW_ID=...
DIDIT_WEBHOOK_SECRET=...
DIDIT_ENVIRONMENT=sandbox        # 'live' in production (enforced at startup)
APP_BASE_URL=https://your-domain # callback URL is built from this
IDV_PRIVACY_CONTACT_EMAIL=privacy@your-domain
```
Then apply the migration:
```
flask --app run db upgrade
flask --app run db current          # should show c7f3a91d5e20 (head)
```
Sign in, open the dashboard → **Identity verification**.

**Rollback**
```
flask --app run db downgrade 4b1d2288b22d   # drops ONLY identity_verification_events and identity_verifications
```
This permanently deletes verification records: back up first. To switch the feature off *without* touching
the database, set `IDV_ENABLED=false` (every `/identity/*` route then returns 404).

### 3.3 Staff sign-in: the Biometric Authentication workflow

Staff sign in with **email → Staff ID → live selfie**. The selfie is checked by Didit's
**Biometric Authentication** product, which compares a returning person's live face with the portrait it
stored during their ID verification. No document is re-scanned and Laundrix keeps no face data.

1. Didit Console → *Workflows → Create workflow* → choose the **Biometric Authentication** type
   (Didit's docs call it `BIOMETRIC_AUTHENTICATION`). Copy its **Workflow ID**.
2. Put it in `.env` as `DIDIT_BIOMETRIC_WORKFLOW_ID` (the ID-verification workflow stays in `DIDIT_WORKFLOW_ID`).
3. The webhook destination you already created is reused.

How the pieces fit:

* **Onboarding (once):** `create-staff` prints a Staff ID and a single-use link. The person opens the link,
  confirms their Staff ID, agrees to the notice, then completes the normal Didit ID verification
  (ID photo + liveness + face match). That is what creates the stored portrait.
* **Every sign-in:** Laundrix starts a Biometric Authentication session using the *same* person reference
  (`vendor_data = laundrix:<user_id>`), so Didit knows which stored portrait to compare against.
* **Fails closed:** if `IDV_ENABLED` is false or `DIDIT_BIOMETRIC_WORKFLOW_ID` is missing, `/staff/*` shows
  "unavailable" (HTTP 503). It never falls back to a weaker sign-in.

**Cost:** Didit's product page lists Biometric Authentication at about **$0.10 per authentication** (vendor-stated).
I could not confirm whether any free allowance covers it, so check your Didit balance/pricing. Each staff sign-in is
one authentication; e.g. 5 staff × 26 working days ≈ 130 sign-ins ≈ $13/month at that price.
`IDV_BIOMETRIC_MAX_PER_HOUR` (default 6) stops someone who has stolen a Staff ID from running up your bill.

**Trade-off:** this adds one redirect to Didit's page per sign-in. Sessions last `SESSION_LIFETIME_MINUTES`
(default 8 hours), so a normal shift is one selfie.

### 3.4 Moving existing staff off AWS Rekognition (one time)

Their Staff IDs stay valid; only the face step changes.

```
flask --app run db upgrade                       # adds identity_verifications.purpose, drops the 3 Rekognition columns
flask --app run new-enroll-link sam@example.com  # repeat for each active staff member
```
Send each person their link. Until they complete it they get "Your identity verification isn't finished yet"
at step 2. Admins who sign in with Google are unaffected. **Back up `staff_credentials` before upgrading**: the
dropped columns held Rekognition references and cannot be restored (downgrade only recreates empty columns).

### 3.5 Retiring AWS Rekognition (privacy clean-up)

Do this once the new flow works; don't leave biometric data sitting in AWS.

```
aws rekognition delete-collection --collection-id laundrix-staff --region <your-region>
```
This deletes the collection and every face in it. Then in the AWS console (IAM): delete the access key and the user
`laundrix-app`, and delete the policy `LaundrixRekognitionAccess`. Finally remove `FACE_PROVIDER`,
`FACE_MATCH_THRESHOLD`, `AWS_*` and `REKOGNITION_COLLECTION_ID` from your `.env` (they are ignored now). The `boto3`
package is no longer required. Use your actual collection ID and region if you changed the defaults.

## 4. Operations

| Command | Purpose |
|---|---|
| `flask --app run idv-status EMAIL` | show a user's attempts and statuses |
| `flask --app run idv-reconcile` | poll Didit for attempts whose webhook may have been missed (cron every ~10 min) |
| `flask --app run idv-purge [--days N] [--dry-run]` | retention clean-up (ID records by `--days`; sign-in face checks after `IDV_BIOMETRIC_RETENTION_DAYS`) |
| `flask --app run create-staff EMAIL --name "…"` | new staff: prints a Staff ID (once) and a single-use onboarding link |
| `flask --app run new-enroll-link EMAIL` | new onboarding/re-verification link (keeps the Staff ID) |
| `flask --app run reset-staff EMAIL` | lost Staff ID: new ID, clears lockout (identity verification kept) |
| `flask --app run staff-status EMAIL` | verified? locked? link pending? last sign-in |
| `flask --app run deactivate-staff EMAIL` | offboarding (then delete their data in the Didit console) |

Didit retries failed deliveries only twice (5xx/404), so schedule `idv-reconcile`.

## 5. Privacy and legal considerations (Philippines) — draft, not legal advice

* **What Laundrix stores:** status, coarse reason codes, document *type*, consent version/time,
  timestamps, audit events. **Not stored:** ID/selfie images, ID numbers, names, birth dates, face data,
  scores. Those stay with Didit.
* **Still personal data:** government-issued IDs/numbers count as *sensitive personal information* under
  the Data Privacy Act (RA 10173), and biometric data is commonly treated as sensitive too. Not storing the
  images reduces your exposure; it does not make you a non-participant. You remain the *personal
  information controller* and stay accountable for data you outsource to Didit (the processor).
* **Consent is not enough by itself.** You also need a defensible purpose and proportionality (why do you
  need ID + face checks?), notice, and security. For **employees**, consent may not be truly free because of
  the power imbalance: the consent page says participation is voluntary and to ask for an alternative; make
  sure an alternative really exists.
* **Do before going live:** a Privacy Impact Assessment; a written data-processing agreement with Didit;
  find out where Didit stores/processes data and how long it keeps it (set retention in the Didit console),
  because that is a cross-border transfer; appoint/check your Data Protection Officer and whether NPC
  registration applies to you; keep a breach plan (the NPC expects notice within 72 hours of knowing of a
  notifiable breach); have a way to handle access, correction, deletion and consent-withdrawal requests.
* The consent text (`consent.html`, version `CONSENT_VERSION` in `services.py`) is a starting draft.
  Have it reviewed, and bump the version whenever it changes.
* **Face data is now processed at every staff sign-in**, not just once. Make sure the consent notice, your
  privacy notice and your data-processing agreement with Didit all say so, and set Didit's retention accordingly.
* **Offboarding:** `deactivate-staff` stops sign-in but does not delete what Didit holds; delete it in the
  Didit console when your retention policy requires.
* **Provider-side deletion:** I did not verify a Didit API for deleting a session's stored data. Use the
  Didit console / their support, and confirm in your agreement.

## 6. Security measures implemented

* API key only on the server; never rendered, logged, or sent over plain HTTP (`https://` enforced).
* Webhook: HMAC-SHA256 **X-Signature-V2** over canonical JSON, constant-time compare; `X-Timestamp`
  **and the signed body `timestamp`** must be within 5 minutes (the header alone is unsigned); `event_id`
  unique in the DB (duplicates/replays are no-ops); `environment` must match `DIDIT_ENVIRONMENT`;
  `vendor_data` must match the session owner; Didit's console "test" deliveries are never applied.
* Only an `https://*.didit.me` hosted URL is ever redirected to.
* CSRF on all user forms; webhook exempt but signature-protected; rate limits on start/refresh/return/webhook.
* Per-user ownership enforced inside the SQL query; other people's records return 404.
* Attempt limit per user (`IDV_MAX_ATTEMPTS` per `IDV_ATTEMPT_WINDOW_HOURS`); provider errors don't count.
* Production refuses to start with `DIDIT_ENVIRONMENT=sandbox` (a sandbox app returns mocked approvals).
* Staff face check: the result is accepted only from Didit's signed webhook or a server-side API call
  (the return URL's query string is ignored); the approval must be newer than the sign-in attempt; a face
  check can only be completed by the wizard that started it; a provider outage or an abandoned check is never
  counted as a failed match; 3 mismatches end the attempt and feed the account lockout; face checks per person
  per hour are capped.
* The staff portal fails closed without Didit. Camera access is denied to Laundrix's own pages
  (`Permissions-Policy: camera=()`); the camera is used only on Didit's page.

## 7. What has and hasn't been tested

| Area | Status |
|---|---|
| Status mapping, transitions, reason-code extraction (`tests/identity/test_statuses.py`) | **Executed** (unittest) |
| Webhook signature / replay logic (`test_signature.py`) | **Executed** (unittest) |
| Didit client against a *fake* HTTP layer, incl. the biometric workflow override (`test_didit_client.py`) | **Executed** (unittest) |
| Deliberate-breakage (mutation) checks of the above | **Executed** |
| Template rendering for every status, escaping | **Executed** (Jinja) |
| Application flow, webhook endpoint, ownership, retry limits, CSRF, purge (`test_flow.py`) | Written; **not executed** (needs Flask, SQLAlchemy, pytest) |
| Staff portal: enrollment, sign-in, face outcomes, lockout, cost cap, CLI (`test_staff_portal.py`) | Written; **not executed** (needs Flask, SQLAlchemy, pytest) |
| Migration chain up/down on SQLite + model/migration parity (`test_migration.py`) | Written; **not executed** (needs SQLAlchemy, Alembic) |
| Real Didit sandbox (`tests/integration/test_didit_sandbox.py`) | Written; **not executed** (needs network + your sandbox key) |
| Real MySQL (`laundrix_db`) migration | **Not executed** |
| Real Philippine ID documents | **Not tested** |
| Didit Biometric Authentication end to end (real portrait comparison) | **Not tested**: needs your Didit account |

Run everything on your machine:
```
pip install -r requirements.txt
pytest                                   # unit + app tests (integration skipped)
DIDIT_SANDBOX_API_KEY=... DIDIT_SANDBOX_WORKFLOW_ID=... pytest -m integration tests/integration
```
All unit/app tests use **fake provider responses**. They prove how Laundrix reacts; they do not prove
Didit behaves that way.

## Sources
* Didit: docs.didit.me (API full flow, webhooks, verification statuses, sandbox testing, pricing);
  didit.me/solutions/countries/philippines
* Persona: withpersona.com/pricing, docs.withpersona.com (government ID verifications, webhooks)
* Sumsub: docs.sumsub.com (self-service trial, test in sandbox, authentication)
* Veriff: veriff.com/demo (pricing/trial terms), help.veriff.com plans description
* Data Privacy Act of 2012 (RA 10173) and its IRR; National Privacy Commission
