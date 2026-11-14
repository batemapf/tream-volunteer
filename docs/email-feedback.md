# Bounce, complaint and delivery feedback

Tream mail uses SES configuration set `tream-dev`. Its event destination publishes delivery, bounce, complaint, rejection, rendering-failure and delivery-delay events onto the regional default EventBridge bus. The Tream rule matches its configuration-set tag so unrelated applications in this AWS account are not processed. No open/click tracking is enabled.

The feedback Lambda stores a minimal private provider receipt for 30 days. Permanent bounces and complaints create a suppression keyed by SHA-256 of the normalized email address. The suppression contains a reason, timestamp and expiry, not a plaintext contact address. Suppressions expire after 27 calendar months; soft/undetermined bounces and delivery delays do not permanently suppress. Duplicate events are safe. Bookings and roster entries are never canceled by email failures.

Before every eligible send, the worker performs a strongly consistent suppression read. Suppressed recipients are skipped and their outbox payload is cleared. If the suppression lookup fails, sending fails closed and the normal retry policy applies. Already in-flight sends cannot be recalled; feedback is asynchronous. SES configuration-set suppression for BOUNCE and COMPLAINT provides an additional provider-side layer without changing the account's default configuration for other applications.

EventBridge target failures and exhausted Lambda processing retries go to encrypted SQS queue `tream-dev-feedback-failures`, retained for 14 days. CloudWatch alarms `tream-dev-feedback-failures` and `tream-dev-feedback-errors` expose processing failures. These alarms currently appear in CloudWatch; no email/SMS alarm subscription is configured. Before wider launch, connect an owner-monitored alert destination.

Operations:

- Check the SES configuration-set reputation metrics and CloudWatch alarms before volunteer campaigns.
- If the failed-event queue is nonempty, fix the processing problem and replay those events through the feedback Lambda. Do not discard them before suppression has been applied. Queue payloads may include provider mail metadata and must stay private.
- Suppression is automatic; do not repeatedly resend to a hard-bouncing address or an address that complained. A volunteer can correct their contact details with the organizer. Deliberate removal of a suppression requires owner review and, if applicable, removal from SES's suppression list too. No public suppression-removal endpoint exists.
- The manually dispatched `Test SES bounce and complaint handling` workflow sends only to AWS's success/bounce/complaint simulator addresses, verifies real EventBridge feedback and suppression persistence, and removes its synthetic records. It does not email the owner or volunteers. Unit checks verify that suppressed recipients never reach SES and suppression-read errors fail closed.

Public recipient delivery remains restricted to the owner inbox. This change does not open public email sending or enable organizer broadcasts. The existing confirmation/change/cancel workflow continues to use the same outbox and private management links.
