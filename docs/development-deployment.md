# First AWS development slice

## Scope

Terraform in `infra/app` provisions the public static board, private S3 origin, CloudFront, HTTP API, Python Lambda, bounded runtime IAM role, DynamoDB on-demand storage with TTL/PITR and short-retention logs. Names use `tream-dev-*`; the existing Sites prototype remains separate.

GitHub Actions uses the existing `production` trust environment to assume the deployment role, but uses **development/terraform.tfstate** in the bootstrap bucket. It does not write production application state. Pushes touching app/backend/infrastructure or manual workflow dispatch deploy this development environment, serialized by workflow concurrency.

Initial draft shifts are imported only if missing. A deploy never overwrites an existing shift, roster or revision. No real schedule has been approved. This environment is public and accepts shared test bookings; use sample contact details.

## Implemented

- Shared public schedule with explicitly projected fields; no contact email, full private name, participant IDs or management credentials in public responses.
- Server-side attendance rules, configurable overflow, simultaneous capacity limits and optimistic transactional retries per shift.
- Batch API supporting multiple participants with a shared email; results per selection so failures do not roll back successful selections.
- Per-selection idempotency: the same request returns its original booking; a reused key with different details fails.
- Client generates a 256-bit management credential before submission; server stores only its hash. Browser saves the credential locally for development management. GET management access reads only; cancellation requires an explicit authorized POST and origin validation.
- Notification intent saved atomically as a disabled private outbox record. No email worker/provider send permissions are enabled on this API role.
- Half-open arrival/departure intervals, local event timezone converted to UTC, per-record 27-calendar-month expiry and public named roster cutoff after the event.
- Unit tests and deployed AWS smoke tests; concurrent last-space contenders, partial departures, partial batch success, authorization and private-response projection. Smoke records are removed afterward.

## API

- `GET /health`
- `GET /schedule`
- `POST /bookings`: `{ email, selections: [{ shiftId, participantId, name, shareName, start, end, idempotencyKey, manageToken }] }`. Hours are local numeric hours for the shift date in this draft interface; records also store UTC timestamps. Maximum 20 selections.
- `GET /bookings/{id}` with `Authorization: Bearer <manageToken>`
- `POST /bookings/{id}/cancel` with the same authorization and matching Origin

The server checks interval boundaries, configured increments/minimums/full-shift rules and capacity. Origin validation is a browser protection, not identity verification or a substitute for abuse controls.

## Still to implement before using for real volunteers

- Multi-selection/family cart UI (batch support exists in the API; the UI still confirms one row at a time).
- Organizer Cognito authentication, schedule/policy editing, private contact view, overlap review and CSV export are implemented in the next development iteration; see organizer-guide.md. Permanent organizer accounts still require the owner setup.
- Sender identity/DNS configuration, SES production access, delivery processing, email-link issuance/resend/revocation and reminders; outbox records cannot simply be enabled as an email worker without the management-link issuance design.
- Group/single/all recipient preview and private saved drafts are implemented in the organizer desk; real sending, opt-outs and annual-outreach preferences remain.
- Manage-link time edits, token recovery/revocation and email-based cross-device access. Development local credential loss currently requires organizer assistance; it is not email recovery.
- Scheduled deletion (DynamoDB TTL is eventual), backup/export lifecycle controls satisfying the 27-month maximum, a restore drill and final retention rules.
- Final schedule, organizer identities, operational alert destinations, launch review, abuse controls and production environment.

Development safeguards (TLS, public projection, transactional booking checks, scoped runtime permissions and API throttling) do not mean this slice is production-ready. No credentials, PII, Terraform plans or state should be committed to Git.

## Local checks

```sh
python3 -m unittest discover -s backend/tests -v
node --check public/app.js
terraform -chdir=infra/app init -backend=false
terraform -chdir=infra/app validate
python3 -m http.server 8000 --directory public
```

Local `public/config.js` selects the original browser-local demo. Deployment generates a config file with the AWS API endpoint and uploads it without committing that generated URL configuration. Private browser management records are stored under a separate key from the local demo.


## First verified deployment

Board: https://dy2majdy4ufxo.cloudfront.net

API: https://saocxbe6xa.execute-api.us-east-2.amazonaws.com

Initial workflow: https://github.com/batemapf/tream-volunteer/actions/runs/43355811185

Terraform created 21 resources successfully using the configured OIDC role. Deployed smoke tests passed (partial batch acceptance, private projection, idempotency, authorization, cancellation, five contenders for one space and departure-boundary capacity). Local unit coverage was expanded to 16 tests including HTTP handler behavior.

A browser test against AWS verified signup, the roster from an independent browser context, hidden private name/email, cancellation and desktop/mobile rendering. The automation browser lacked the environment proxy's root CA in its Chromium certificate store; the test used Playwright's HTTPS-verified request routing through the inherited proxy/CA configuration. TLS verification was not disabled. An independent curl request also verified HTTPS and the site's security headers.

Live development bookings are shared; browser management credentials are still device-local until the email recovery flow exists. API smoke records are deleted; browser tests use synthetic contacts and cancel their test bookings.


## Organizer iteration

See [organizer guide](organizer-guide.md). Cognito password login, group authorization, granular coverage, revision-protected edits, private contacts, overlap review, safe CSV export, authorized cancellation and single/group/all message previews with saved drafts are implemented. The sparse DynamoDB draft index is private; no private records are added to public schedule responses. Sending is still disabled.

The deployment workflow tests a temporary user's first-password challenge and group membership, then exercises the real organizer UI in Chromium and deletes the temporary user and synthetic private test data. Audit entries remain private under configured retention. One owner-created permanent user is needed to use the desk interactively.
