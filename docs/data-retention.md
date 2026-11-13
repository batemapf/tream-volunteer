# Data retention and annual outreach

Confirmed ceiling: **2.25 years (27 calendar months)**, to support re-engaging volunteers in future years. User owns operation and costs.

## Proposed implementation defaults

- For event-linked participant/booking data, calculate `expiresAt` at event end plus 27 calendar months. This clock is an implementation default pending any correction; it is not measured from arbitrary administrative edits or email sends.
- Contacts participating in a later event can remain for that later event's retention window, but older expired booking details and consented public roster entries are still deleted on their original schedule.
- At the event's conclusion, stop serving historical named rosters publicly by default. Private records may remain for the retention period; retaining records does not imply keeping them publicly searchable for 27 months.
- Maintain annual-outreach preference and opt-out separately from operational booking notifications. Offer a clear annual-invitation choice and unsubscribe path. Do not reactivate outreach on a routine record edit. Do not put private management links in public communications.
- Store only fields needed for signup, administration and outreach. Logs contain no raw management tokens, message bodies or unnecessary contact data, and have shorter configured retention. Management tokens and notification payloads expire much sooner than the general data ceiling.
- Use application-level expiry checks and scheduled deletion of expired private/public records, outbox payloads, exports and any retained message content. DynamoDB TTL is a cleanup fallback, not a precise deadline; it can delete asynchronously after expiry.
- Retain only non-identifying aggregate event counts after individual data expires.

## Backups and recovery

The 27-month ceiling includes recoverable copies; active-record deletion alone does not erase backups. Configure finite backup/PITR retention and incorporate backup lifetime into the deletion schedule so no retained personal data exceeds the ceiling. Do not create indefinite manual snapshots or exports. Specify the concrete recovery-window/expiry behavior with the infrastructure implementation, and verify it before launch.

A restore must apply expiration and suppression rules before serving the app or sending messages. Document how organizer-downloaded CSV files are deleted as well; AWS cannot enforce deletion on copies downloaded to someone's device.

Opt-out suppression records should be minimal. Define their expiry and re-consent behavior consistently with the 27-month ceiling rather than retaining raw email indefinitely by accident.
