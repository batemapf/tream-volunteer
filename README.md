# Tream Volunteer

Spreadsheet-style volunteer signup prototype for the Brent Elementary Holiday Sale.

Parents can browse shifts, staffing gaps and consenting volunteers, then sign up through a structured form. The board itself is read-only.

## Run locally

No build or dependency installation is needed. From the repository root:

```sh
python3 -m http.server 8000 --directory public
```

Open http://localhost:8000.

## Current scope

- Filter shifts by day, job type and staffing need.
- View individual arrival and departure hours.
- Choose partial shifts where allowed.
- Optionally display first name and last initial; names are private by default.
- Create and cancel demo signups stored in the current browser.

This is a prototype with fictional volunteers. There is no shared database, server-side capacity enforcement, authentication or email delivery. Submitted email addresses are not retained or sent anywhere. Use sample details.

## Project notes

See [feature notes](docs/feature-notes.md) and [open decisions](docs/open-decisions.md) before implementing production behavior. The spreadsheet experience and a custom AWS backend are selected. See [technical plan](docs/technical-plan.md) and [email options](docs/email-options.md) for the proposed implementation and SES recommendation.

Public feedback prototype: https://brent-tream-planner.batemapf.chatgpt.site

The public prototype is deployed separately through Sites. This repository does not yet have automated hosting or deployment configured.

AWS deployment setup and IAM requirements: [deployment access](docs/aws-deployment.md). Data lifecycle: [retention policy](docs/data-retention.md).
