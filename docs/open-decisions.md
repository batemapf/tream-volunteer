# Open decisions

The selected experience is a read-only spreadsheet-style board with form-based signup. No required volunteer authentication is currently planned.

## Product

- Confirm whether a publicly accessible roster with optional first name and last initial is acceptable.
- Identify which jobs allow partial attendance and their minimum commitments.
- Define “all shift” as a specific job window; confirm the wording and behavior.
- Confirm multiple dates/jobs in one submission and separate hours per selection.
- Distinguish flexible staffing targets from hard capacities.
- Decide whether parents can register other named family members using one email.
- Define coverage presentation, especially gaps hidden by partial attendance.
- Confirm manual organizer reconciliation of matching-email overlap flags.
- Set the minimum organizer tools: shift editing, private contacts, conflict review, roster export and targeted notifications.

## Technical

- Evaluate Airtable against the agreed workflow before choosing a custom backend.
- Keep private contact records separate from the public roster/API.
- For hard limits, enforce capacity atomically; define partial success versus all-or-nothing for multi-job submissions.
- Obtain the final schedule and reconcile volunteer versus public sale hours and locations.
- Choose a transactional email provider and a sender domain with accessible DNS.
- Implement secure, revocable management links and a resend path. Link visits must not mutate bookings.
- Choose organizer authentication and permissions.
- Establish account ownership, operating costs, backups, maintenance and data retention.

These are unresolved questions, not implementation requirements. See feature-notes.md for context and prototype history.
