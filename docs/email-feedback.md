# Bounce, complaint and delivery feedback

Tream mail uses SES configuration set `tream-dev`. Its event destination publishes delivery, bounce, complaint, rejection, rendering-failure and delivery-delay events onto the regional default EventBridge bus. The Tream rule matches its configuration-set tag so unrelated applications in this AWS account are not processed. No open/click tracking is enabled. The sale domain uses structured feedback rather than forwarded bounce emails; the shared Gmail identity's forwarding settings are unchanged.

The feedback Lambda stores a minimal private provider receipt for 30 days. Permanent bounces and complaints create a suppression keyed by SHA-256 of the normalized email address. The suppression contains a reason, timestamp and expiry, not a plaintext contact address. Suppressions expire after 27 calendar months; soft/undetermined bounces and delivery delays do not permanently suppress. Duplicate events are safe. Bookings and roster entries are never canceled by email failures.

Before every eligible send, the worker performs a strongly consistent suppression read. Suppressed recipients are skipped and their outbox payload is cleared. If the suppression lookup fails, sending fails closed and the normal retry policy applies. Already in-flight sends cannot be recalled; feedback is asynchronous. SES configuration-set suppression for BOUNCE and COMPLAINT provides an additional provider-side layer without changing the account's default configuration for other applications.

EventBridge target failures and exhausted Lambda processing retries go to encrypted SQS queue `tream-dev-feedback-failures`, retained for 14 days. CloudWatch alarms `tream-dev-feedback-failures` and `tream-dev-feedback-errors` expose processing failures. These alarms currently appear in CloudWatch; no email/SMS alarm subscription is configured. Before wider launch, connect an owner-monitored alert destination and include SES provider-side suppression entries in the retention cleanup (SES does not expire those automatically).

Operations:

- Check the SES configuration-set reputation metrics and CloudWatch alarms before volunteer campaigns.
- If the failed-event queue is nonempty, fix the processing problem and replay those events through the feedback Lambda. Do not discard them before suppression has been applied. Queue payloads may include provider mail metadata and must stay private.
- Suppression is automatic; do not repeatedly resend to a hard-bouncing address or an address that complained. A volunteer can correct their contact details with the organizer. Deliberate removal of a suppression requires owner review and, if applicable, removal from SES's suppression list too. No public suppression-removal endpoint exists.
- The manually dispatched `Test SES bounce and complaint handling` workflow sends only to AWS's success/bounce/complaint simulator addresses, verifies real EventBridge feedback and suppression persistence, and removes its synthetic records. It does not email the owner or volunteers. Unit checks verify that suppressed recipients never reach SES and suppression-read errors fail closed.

Transactional team-test delivery now accepts real volunteer inboxes; organizer broadcasts remain disabled. The existing confirmation/change/cancel workflow continues to use the same outbox and private management links.

## Verification — November 14, 2026

Deployment 43612025694 passed 44 unit checks plus live application checks. Workflow 43612157859 passed real SES simulator delivery, permanent bounce and complaint publication through EventBridge; suppression was false for delivery and true for bounce/complaint. Synthetic records were removed. No messages were sent to human recipients by that verification workflow.

## Inbox alerts

CloudWatch alarm/recovery actions target SNS topic `tream-dev-operations`, with an email subscription for the owner. This route is independent of SES and the booking worker. It covers feedback-handler errors, failed feedback events, worker crashes, and terminal notification-delivery failures. Individual normal bounces do not trigger operations emails. Terminal notification failures emit a structured, contact-free log metric; transient retries do not trigger that metric.

The owner must confirm the AWS SNS subscription in Gmail. Until confirmation, the topic cannot deliver email alerts. Deployment needs the additional narrowly scoped SNS permissions in `infra/bootstrap/deploy-alerts.json` on `tream-github-deploy`; no application runtime SNS permissions are required. After confirmation, validate one ALARM/recovery transition without breaking real delivery. An OK transition means the metric window is healthy; it does not prove a previously failed notification was replayed or a failed-event queue was drained.

Alert rollout status: deployment 43612599011 was blocked specifically by `SNS:CreateTopic` on `tream-dev-operations`; the deployment role has no SNS provisioning permission. The final narrowly scoped policy is `infra/bootstrap/deploy-alerts.json`, to attach as an inline permissions policy to IAM role `tream-github-deploy`. The failed apply updated the contact-free failure metric/logging, but did not create an alert subscription. SES preflight 43612621256 separately confirmed production access, DKIM and custom MAIL FROM are all enabled/verified.

Operational alerts are explicitly deferred: `enable_operations_alerts` defaults to false, leaving SNS resources unprovisioned and alarm actions empty. After the SNS deployment permission is added, set that variable true and confirm the owner subscription. This does not block team-test transactional delivery.
