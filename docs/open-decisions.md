# Decisions and remaining setup

Updated November 12, 2026. This supersedes conflicting proposals in feature-notes.md.

## Confirmed product decisions

- Spreadsheet-style, publicly accessible, read-only volunteer board; signup through structured forms.
- Optional public first name and last initial are acceptable. Default to private display; public records never include contact details or management credentials.
- Multiple dates/jobs in one submission, with independent hours per selection.
- Multiple named volunteers may share one contact email. Model contact, participant and booking separately. Display-name permission is per participant.
- Attendance rules are configured when loading the schedule, with per-job defaults and per-shift overrides. Actual rules and final schedule come later.
- Capacity is the nominal hard capacity plus a configurable per-job percentage overflow allowance.
- No required volunteer login. Organizer reviews overlap flags manually. Shared email alone must not cause a blocking conflict.
- Organizer tools: shift editing, private contacts, conflict review, roster export, and notifications to one, selected/groups, or all relevant contacts.
- Custom AWS backend; Airtable is no longer under consideration.
- Secure revocable management links, resend flow, and no mutations from link visits.
- Organizer username/password authentication is sufficient; use managed authentication.
- User owns accounts, costs, backups and maintenance. GoDaddy DNS access is confirmed.

## Implementation defaults selected under delegated judgment

- “Entire shift” means that named shift's start through end, shown explicitly. A custom-hours alternative is offered only where the configured attendance rules allow it.
- Public coverage summarizes the minimum/maximum simultaneous staffing, showing where a shift needs help. Detail shows participants' actual hours. Organizer view adds time-by-time counts, deficits and departures; do not let total signup counts imply full-window coverage.
- Time intervals are half-open: arrival counts, departure does not. Store UTC instants plus the event time zone (America/New_York); do not hardcode EST.
- Effective capacity = floor(nominal capacity × (1 + overflow percent / 100)). Default overflow is 0%. Rounding down never exceeds the percentage allowance; show the computed limit to organizers. Track nominal target and effective ceiling separately.
- On a multi-selection request, process selections independently in stable submitted order. Reserve each valid selection atomically, continue after failures, and explicitly return booked/failed results. This accepts available selections without all-or-nothing rejection; it does not optimize a globally largest combination of competing selections.
- Keep successful selections visible; retry only failures. Use request/selection idempotency keys so retries cannot duplicate bookings.
- A shared contact email is a review signal, not proof that two bookings belong to one person. Same participant overlapping themselves gets a stronger flag; neither blocks submission solely for overlap.
- Notification recipients are deduplicated by normalized contact email and sent individually, with no shared To/CC recipient list. Recipient preview and explicit send confirmation apply to single, selected/group, and all sending. Include the relevant family participants and hours.

## Remaining inputs and setup

- Final jobs, shifts, locations, staffing counts, overflow percentages and attendance policies.
- AWS account/region, chosen sender domain/subdomain, sender and monitored reply-to addresses.
- SES production access and sending limits; complete DNS verification and delivery-event configuration.
- Initial organizer users and who can invite/reset other organizers.
- Concrete retention period and backup/recovery settings. Ownership is resolved; these operational values are not yet specified.

See technical-plan.md and email-options.md for recommendations. These documents specify intended production behavior; the hosted prototype remains browser-local and does not implement the backend.
