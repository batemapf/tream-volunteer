# Tream volunteer signup — feature notes

Updated November 10, 2026 (America/New_York).

## Status

Paused pending discussion with Dave and Andy. Do not implement these ideas yet. If the project proceeds, the user plans to create a new GitHub repository; migrate these notes there when requested. No repository has been created for this next phase.

Public feedback prototype: https://brent-tream-planner.batemapf.chatgpt.site
Sale context: https://brentholidaysale.com/

## New feedback from Dave

Captured from the supplied text-message screenshot; ideas for discussion, not finalized requirements:

- Select multiple dates on the first page so volunteers do not have to restart the flow for each day.
- Narrow down the time choices. Exact increments and how choices depend on the selected day/job remain to be decided.
- Offer an “all shift” option. Clarify whether this means an entire named job shift or all available hours on a selected day; do not assume it means all day.
- Dave wants to discuss next steps with the user and Andy tomorrow (November 11, 2026); no meeting time is confirmed.

## Current direction

- Simple, linear, form-style volunteer experience: availability → job choices → details → confirmation. Back navigation preserves choices.
- Keep the parent-facing UI clean, with little annotation. No organizer view in the feedback prototype.
- Support exact arrival/departure times, especially “I can work the morning, but only until 11.” Count presence only during committed intervals.
- Availability-first signup, with role-specific constraints where necessary. Delivery full-window requirements in the prototype are draft rules for review, not confirmed policy.
- Seed production storage with the actual jobs, dates, capacities, and open slots.
- Enforce slot capacity and concurrency on the server with atomic database operations; repeated submissions must not create duplicate bookings.
- Current preference: no required volunteer login. Parents supply name and email. Potential personal overlaps can be flagged for organizers to reconcile manually rather than blocking signup or requiring authentication.
- Clarify treatment of shared family email addresses and signups for other people before implementing conflict matching.
- Confirmation and reminder emails provide exact committed hours and a secure per-signup change/cancel link. Consider calendar attachments and a way to resend signup links.
- Opening an email link must not itself cancel or modify a booking; require confirmation on the resulting page so email scanners cannot trigger changes.
- Production email requires a verified sender on a domain the team controls. Access to brentholidaysale.com DNS is unknown; a PTA domain or new team-owned domain could be used instead. Configure provider-required SPF/DKIM and DMARC; track bounces and delivery failures.
- Passwordless email-code login remains an alternative if a unified personal schedule becomes valuable enough to justify login friction. It is not the current requirement.

## Prototype limitations

- Public; Dave does not need an OpenAI account.
- Browser-local sample state only. No shared production database, real signup submission, email delivery, or authentication.
- Organizer screens were removed. Hard browser-local overlap blocking was removed to match the manual-reconciliation direction.
- Flow and booking logic were checked programmatically. Browser visual verification was unavailable in the environment.

## Questions for Dave and Andy

- Should each selected date have independent arrival/departure hours, with an optional “same hours” shortcut?
- Which time choices should be offered for each day and job?
- What exactly should “all shift” select, particularly when multiple dates are selected?
- Which jobs accept partial attendance, and which require a minimum or full commitment?
- Should several selected jobs be confirmed together? If one fills during submission, should the remaining jobs still be booked?
- Which person/domain can support authenticated outgoing email, and who will maintain the tool after the sale?

These questions are discussion prompts, not additional approved features.

## Spreadsheet-board pivot — November 11, 2026

User requested a clickable alternative after feedback from a frequent Brent volunteer: see who else is volunteering, which jobs need help, and which shifts are empty. Dave's concerns with an actual public spreadsheet are privacy/phishing and accidental edits to shared structure.

Implemented on the existing public prototype URL:
- Read-only shift table with all days, role filters, and a needs-help filter.
- Coverage counts reflect actual time present; ranges indicate variation during the shift.
- Participant details show individual arrival and departure hours.
- Form-driven signup protects table structure; supports partial shifts where allowed.
- Public display names are optional, off by default, limited to first name and last initial. Anonymous participants still count toward staffing. This minimizes exposure but does not make opted-in names unidentifiable.
- No contact details shown publicly. Demo does not retain submitted email/full name; only the chosen public label and booking hours are stored locally.
- Local demo management allows cancellation. No organizer view or authentication introduced.

Future production architecture must keep private contact records separate from the public roster response; hiding columns in the UI is insufficient. Public-board consent language and whether a public roster is acceptable remain for Dave/Andy review. No real backend/email delivery or real concurrent-booking guarantee is implemented in this demo. Programmatic privacy, capacity, filters, and partial-coverage checks passed; browser visual QA was unavailable.

## Requirements confirmed — November 12, 2026

User resolved the product/backend questions. See open-decisions.md for the authoritative decisions and selected defaults; technical-plan.md for the proposed AWS design; email-options.md for the SES recommendation and alternatives. Earlier Airtable/authentication proposals are historical context, not current requirements. Hosted prototype behavior remains unchanged by this documentation update.


## Organizer desk deployed

A Cognito-protected organizer desk is live at https://dy2majdy4ufxo.cloudfront.net/organizer.html. Includes granular coverage, revision-protected schedule/policy editing, private contacts, family/same-person overlap review, CSV export, organizer cancellation and individual/group/all recipient previews with saved/reloadable private drafts. Sending remains disabled. Permanent organizer accounts are created by the owner in Cognito pool tream-dev-organizers (us-east-2_ppF5IKYbw) and added to organizers. See organizer-guide.md for setup and verified release evidence. Public volunteer signup remains account-free; multi-selection/family cart UI and volunteer email management remain future work.

## Responsive volunteer board — November 13, 2026

The desktop spreadsheet is preserved. At 900px and below, the same rows become compact cards grouped by day, keeping job, hours, staffing coverage, consenting volunteer names and the signup action visible without horizontal data scrolling. Day/job/needs-help filters remain available in a sticky toolbar; the day strip scrolls independently and keeps the selected day visible. The signup dialog uses larger touch targets, 16px input text and a viewport-bounded scroll area. Privacy, backend rules and organizer workflows are unchanged.

Responsive browser regression covers page widths 320–1440px, visible 44px mobile signup actions, local mobile signup/cancellation, and preserved desktop headers. Sample data is used only inside the automated browser fixture; no shared bookings are created by this responsive test.

## November 14, 2026 updates

Added optional per-shift configurable task preferences for lot volunteering; refreshed the public and organizer branding using the original Brent bear, locally hosted Fjalla One heading font, white background and requested full 2026 sale title. Added HTML and HTTP noindex directives and robots.txt. See tasks-branding-and-visibility.md for source assets, configuration/migration semantics and crawler limitations. Preferences remain private; no sub-job staffing quotas or qualification claims are inferred.

## Mobile day filters and form copy cleanup

Removed “Join this shift” from the signup form. Replaced the horizontally scrolling mobile day strip with a three-column wrapping grid (two rows for the current five-day schedule plus All days). All day choices remain visible with 44px touch targets. Tablets use six columns where space permits; desktop behavior is preserved. Removed obsolete horizontal day-scroll code. Responsive regression checks now explicitly assert that every day button fits without horizontal scrolling at 320–900px.

### Signup copy, name visibility, and lot tasks

Removed the form roster heading and private-name explanatory copy. New signups show first name and last initial by default; checking “Keep my name private on the board” opts out. Existing signup privacy remains unchanged. Lot task choices are Sales, Cashiering, Greenery Management, Lot Maintenance/Inventory Replenishment, and Tree Prep (Chainsaw/Baling/Loading). The schedule seed migrates only the exact original draft task list, preserving custom choices and existing booking records.

### Compact shift summaries

Removed name previews and the roster column from mobile cards and desktop spreadsheet summaries. Full rosters remain in shift details. Mobile actions sit beside the title, and coverage ends the card without an extra footer row.

### Event heading and signup totals

Consolidated the public header into a single event H1 with date/location and explicit Brent PTA organizer attribution. Organizer masthead also identifies Brent PTA. Summary cards/table count each booking once, including partial attendance, and label this “Signed up”; the progress bar follows signup totals. Capacity enforcement, needs-help filtering, and organizer time coverage continue using actual attendance intervals.

### Owner-only live email and rebooking

Booking, change and cancellation emails are enabled only for the owner's verified SES inbox. Management links work across browsers without a login and never mutate on page visits. Volunteers can change shifts/hours atomically, cancel with confirmation, and resend from a working link. The real AWS/SES and mobile management workflow passed on November 14; see email-testing.md for receipt evidence, scope and remaining public-launch email work. Historical disabled outbox records remain disabled. Organizer broadcast drafts remain unsent.
