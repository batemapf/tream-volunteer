# Email as the volunteer signup record

The public board no longer shows a browser-local My signups list or persists signup credentials in localStorage. Old app receipt keys are removed. A signup success screen shows the submitted email address and an immediate per-booking View/change/cancel link. Confirmation emails remain the durable record. The in-memory local demo resets when reloaded.

Find my signups accepts an email address and always returns the same public response for valid input, including unknown addresses and rate-limited requests. The recovery email privately lists active, unexpired, upcoming commitments for every named participant sharing that email. It includes per-booking links; no signup details are returned on the public recovery endpoint. Requests are limited to one per address per five minutes and ten per source IP per minute (to accommodate shared school/household networks). Suppression checks still apply at delivery time.

Bookings have a normalized SHA-256 contact hash and a private KEYS_ONLY contactHash-createdAt lookup index. The deployment backfill adds that hash to existing records idempotently without changing names, dates, token hashes or statuses. Public roster serialization remains allowlisted and never includes contact hashes or private contact data.

Recovery links use a fresh 256-bit token. Only its hash and contact hash persist in a recovery-access record, with an explicit 24-hour validity check and TTL cleanup. The recovery grant can manage bookings belonging to that contact email, including shared-family commitments. Existing per-booking confirmation links remain valid and are not rotated. Treat recovery emails as private: forwarding them grants access to the shared email's signup records. Canceled bookings cannot be changed. No link visit changes a booking.

The raw recovery token and email/name summary exist only in the private SSE-encrypted outbox until send/final failure; then they are removed. Unsent recovery payloads expire within 24 hours. Large family summaries are split into emails of at most 40 commitments. Recovery creates no organizer account and uses no password or browser-persisted account state.

For a mistyped email or an inaccessible inbox, the public UI offers the organizer contact address. Organizer accounts are separately managed in Cognito; the organizer page is served at /admin, with /admin/ redirecting there and the original organizer.html path retained. Static page access never authorizes private organizer API calls.

## Verified November 14, 2026

Deployment 43632198060 passed all 50 unit checks and live API, /admin Cognito login, mobile and noindex checks. Existing booking contact hashes were backfilled during deployment. Real email workflow 43633461269 passed a fresh-browser Find my signups request, SES summary-email acceptance and payload cleanup, original new/legacy-host management-link viewing, editing/change email, and cancellation/cancellation email. Shared-email participants, cross-household denial, recovery expiry, rate limits, and preservation of primary links are covered by unit checks. A 320px API-mode browser check separately verified the immediate success-screen management link and submitted email address without persistent browser credentials.
