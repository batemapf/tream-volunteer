# Proposed AWS implementation

Target production design. A first AWS development slice is now deployed; see development-deployment.md for verified functionality and remaining work. Production launch is not complete.

Primary AWS region: us-east-2. See [deployment access](aws-deployment.md) for GitHub OIDC/IAM setup and [retention](data-retention.md) for the 27-month ceiling.

## Components

- Static web UI on S3/CloudFront (or Amplify Hosting), preserving the spreadsheet board.
- API Gateway + Lambda for public signup, management-link and organizer endpoints.
- DynamoDB on-demand for schedule, bookings, private contacts, participant records and notification outbox. Use separate public projection records; never return private objects and remove fields in the browser.
- Cognito user pool for organizer username/password login, managed password hashes, sessions and resets. No public organizer self-registration. Authorize organizer API operations server-side.
- SES for email; SQS + Lambda for controlled sending/retries, delivery-event handling and dead-letter review. EventBridge Scheduler for reminders. CloudWatch for errors and operational metrics.
- Terraform infrastructure as code, with separate development/production configuration, private S3 state, native S3 locking and GitHub OIDC deployment. See infra/bootstrap for initial provisioning policies.

## Flexible domain model

- Event: ID, title, timezone, dates, public hours, default location and policy version.
- Job: ID, title, description, role/crew requirements, default attendance policy and overflow percentage.
- Shift: job/event IDs, start/end, location and instructions, nominal capacity, overrides, effective capacity and revision.
- Attendance policy: full-window or flexible; minimum/maximum duration; time-choice increment; allowed start/departure windows; optional predefined windows. Validate combinations and schedule boundaries. Keep additional requirements structured and versioned rather than embedded in UI code. Avoid arbitrary executable rules.
- Contact (private): normalized email, delivery state and timestamps. Normalize conservatively; do not strip plus tags or dots from addresses.
- Participant: opaque ID, private name and contact association, public-name consent and approved display label. Multiple participants per contact; consent is not inferred for all family members.
- Booking: opaque ID, participant/contact references, shift, exact committed interval, status, idempotency identity, policy snapshot/version and timestamps.
- Management access: hashed opaque token, scope, expiry and revocation. Never expose booking/contact IDs as authorization. Contact-wide access is granted only through a message to that contact, not merely by entering their email.
- Notification/outbox: recipient scope snapshot, purpose, booking revision, delivery status and deduplication key. Keep contact content outside the public projection.

Finalize names and indexes with the implementation; these are conceptual records, not a promise of one table per entity.

## Atomic capacity, including partial attendance

Capacity is simultaneous attendance, not total booking count. Read the shift and all active shift bookings consistently, then check a candidate interval against booking start/end boundaries and the effective ceiling. Use a DynamoDB transaction conditioned on the shift's revision to add/update/cancel the booking, increment the revision, and write notification work. Every capacity-affecting writer, including organizer edits, must participate in the same revision protocol. A competing write invalidates the snapshot; reread, recompute and retry a bounded number of times. Do not rely on a browser check or an eventually consistent index for admission.

Use a transactionally checked idempotency record per selection; a retry returns the original result. Keep each selection independent so batch size does not become one large transaction. Return explicit retryable failures if contention persists. Shift policy/capacity edits must detect existing over-capacity commitments and require organizer resolution rather than silently deleting people.

This low-volume approach trades some per-shift serialization for simple exact interval handling. Load/concurrency tests must verify the snapshot/revision protocol, duplicate retries, cancellations and policy changes before launch.

## Privacy and management

Public endpoints provide only approved roster labels, intervals, shift details and aggregate counts. Never ship email, full private name, tokens, internal exports or organizer data in public assets/responses. Private names remain available to authorized organizers.

Management links open a review page. Token exchange/read must not cancel a booking or consume its action merely because a scanner visited. Changes require an explicit validated POST; apply scope checks and protect against CSRF. Use HTTPS, no token logging/analytics, restrictive referrer policy, expiry/revocation and rate-limited resend with a neutral response. Select token lifetime before launch and support replacement links.

CSV exports are organizer-only, escape fields correctly and neutralize spreadsheet formula injection. Keep an audit history of administrative changes and sends. Use reasonable field limits, validation and rate limiting rather than mandatory parent accounts.

## Notifications and recovery

Confirmations summarize successful selections and identify failures separately. Include exact hours and per-booking or appropriately scoped management access. Reminders recheck booking status/revision before sending. Suppress known hard bounces/complaints and surface failures to organizers; signup success is independent of email provider availability because notification work is durably saved with the booking.

Single/group/all notification actions show deduplicated recipients and message preview before sending. Group by event, day, job or shift; preserve family context within each private message. Follow provider limits and record send outcomes. Avoid promising exactly-once delivery: use deduplication and bounded retries to minimize duplicates.

Enable DynamoDB point-in-time recovery and define backup retention, deletion policy and a restore drill before production. The user owns these resources; no provisioning is authorized by this planning update alone.
