# Face Login: setup, calibration and troubleshooting

How it works: **Face Login** button (Staff tab) → browser camera (permission prompt) → live scan with an oval
guide → best of 3 frames is sent to `/auth/face-login` → Didit **Passive Liveness** → Didit **Face Search**
(1:N over your verified users) → the matched `vendor_data = laundrix:<user_id>` is looked up → signed in and
sent to `/dashboard/staff`. Laundrix stores no face images or templates.

## 1. Prerequisites (do these first, they are the usual cause of "low match")

1. **Use a LIVE Didit application key.** Didit sandbox keys skip all processing and return a fixed mock
   result, so a sandbox key can never match your real face. In `.env`: `DIDIT_ENVIRONMENT=live`, with the
   live app's `DIDIT_API_KEY`, `DIDIT_WORKFLOW_ID`, `DIDIT_WEBHOOK_SECRET`.
2. **Face Search needs credits.** Each login costs one Passive Liveness + one Face Search call.
3. **The staff member must be enrolled with the same Didit application**, with an *Approved* ID verification
   whose `vendor_data` is `laundrix:<id>`. Staff created before you switched keys/apps must re-enroll:
   `flask --app run new-enroll-link staff@example.com`.
4. **HTTPS or localhost.** Browsers only allow the camera on `https://` or `http://localhost`.

## 2. Configuration

`.env`:
```
IDV_ENABLED=true
IDV_PROVIDER=didit
DIDIT_ENVIRONMENT=live
STAFF_GOOGLE_LOGIN_ALLOWED=true
FACE_LOGIN_MIN_SIMILARITY=80     # start here while calibrating
FACE_LOGIN_MIN_MARGIN=5          # best person must beat the next different person by this much
```
Apply the DB change and restart:
```
flask --app run db upgrade        # migration b5d1e8c3a7f2 retires the Staff ID column
```
Google: in Google Cloud Console → Credentials → your OAuth client, the redirect URI must be exactly
`<APP_BASE_URL>/auth/callback`. Google only signs in accounts an admin already created (never auto-creates).

## 3. Test it

1. Create/enroll a staff member: `flask --app run create-staff you@example.com --name "You"` → open the
   printed link → set password → finish Didit ID verification → account becomes active.
2. `/auth/login` → **Staff** tab → **Sign in with Face Recognition** → Allow camera.
3. Look at the camera in even, front-facing light. When the oval turns green and the bar fills, it
   captures and signs you in.

## 4. Calibrate the threshold (fixes "my face only gets a low match")

Every attempt logs one line per candidate:
`Face Search diagnostic: reference=laundrix:7, similarity=84.2, ...`
1. Make 5-10 genuine attempts per staff member (different times of day). Note the `similarity` for *their*
   `reference`.
2. Set `FACE_LOGIN_MIN_SIMILARITY` about 3-5 points below the lowest genuine score you saw.
3. Have a different enrolled colleague scan: your `reference` must score below the threshold for them
   (the margin rule also blocks near-ties between two people).
4. Keep it as high as your genuine scores allow. Don't go below ~75 for a login that opens payments.

If genuine scores stay low (<70): re-enroll with a clearer ID photo/selfie (the stored face is what you are
compared to), and check lighting/glasses/mask. If Face Search can't reach acceptable scores, fall back to
Didit's 1:1 **Biometric Authentication** workflow (code kept: `idv.start_biometric_auth`).

## 5. What was changed and why

| Problem | Fix |
|---|---|
| Face Search sent the photo as `image`; Didit's field is `user_image` | `didit.py` |
| Same person matched by several sessions → "multiple candidates" rejection | `face_search.py` groups by user, margin rule between *different* people |
| Declined/other sessions could block valid logins | non-Approved matches are ignored |
| Capture the instant the camera opens (dark/blurry) | warm-up, brightness/blur/motion checks, optional face-position check, best of 3 frames |
| "No face" looked like "service unavailable" | `FaceNotDetected` → friendly 422 message |
| Admin tab had no Google button; staff Google blocked by default | Google button on both tabs; `STAFF_GOOGLE_LOGIN_ALLOWED` default true |
| Staff ID | removed (routes, templates, CLI, column made nullable and cleared) |

## 6. Troubleshooting

| Message / symptom | Cause |
|---|---|
| "Face Login is currently unavailable" (404) | `IDV_ENABLED=false` |
| "temporarily unavailable" (503) | Didit key/credits/rate limit; see server log `Didit POST ... provider_code` |
| "couldn't see a clear face" (422) | no face in frame; lighting/position |
| "couldn't recognise your face" (401) | liveness failed, score below threshold, margin tie, not Approved, or not staff/active. Read the diagnostic log line |
| Camera button disabled | not HTTPS/localhost, or browser blocks the camera |
