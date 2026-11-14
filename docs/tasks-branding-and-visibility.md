# Optional tasks, Brent branding and crawler visibility

## Optional task preferences

Lot shifts offer optional multi-select tasks, initially Cashier, Chainsaw, Sales and Loading. These are preferences, not assignments, qualifications or separate capacity reservations. Leaving every option blank is valid. Only organizers and the signup's own confirmation see the participant's selections; the public roster continues to show only the approved display name and hours.

Defaults are loaded from `backend/job-defaults.json`, keyed by job type (`role`). Each schedule row in `backend/schedule-draft.json` can override `subJobs`, including `[]` to offer no choices. Example:

```json
{
  "subJobs": [
    {"id":"cashier","label":"Cashier","description":"Help at checkout","enabled":true},
    {"id":"loading","label":"Loading","enabled":true},
    {"id":"retired-task","label":"Old task","enabled":false}
  ]
}
```

Up to 32 options are supported. IDs are unique lowercase identifiers (letters/numbers/underscores/hyphens, maximum 60 characters); labels are up to 80 characters, optional plain-text descriptions up to 240. `enabled` defaults to true. Stable IDs make labels editable without reinterpreting historical choices.

The initial import fills a missing `subJobs` field on existing lot shifts, using a conditional update and incrementing the shift revision. It never overwrites an existing option configuration, including an intentional empty list. Future deployment/default changes therefore do not silently replace organizer edits. New shifts receive role defaults unless the row specifies its own choices.

Organizers can also edit the option JSON in the shift editor. Signups validate against the currently enabled choices and store a private ID/label snapshot. Disabling/removing a choice prevents new selections without rewriting past preferences. The private volunteer list and CSV export include the snapshots.

## Branding

Title: **2026 Brent Elementary Christmas Tree and Holiday Sale**.

The public board and organizer sign-in use a white background, straightforward school-event typography and the original Brent bear. The bear is locally hosted at `public/assets/brent-bear.png`; it is not AI-generated or hotlinked at runtime.

Source: https://brentholidaysale.com/cdn/shop/files/Brent_Bear_300x300.png?v=1614335398

The sale site's Fjalla One heading font is also hosted locally. It is distributed under the SIL Open Font License, included at `public/assets/FjallaOne-OFL.txt`; source: https://github.com/google/fonts/tree/main/ofl/fjallaone. Body text uses system Helvetica/Arial. No third-party font requests are needed.

## Crawler exclusions

- HTML pages have `robots` metadata: noindex, nofollow, noarchive, nosnippet, noimageindex.
- CloudFront adds the same `X-Robots-Tag` header to pages and assets.
- Lambda API responses add `X-Robots-Tag`; the API also serves a blocking `/robots.txt`.
- The main site's robots.txt deliberately permits fetching, so search engines can read noindex directives. Blocking crawling can leave externally linked URLs indexed without their content. No sitemap is published.
- Organizer/private API authorization is unchanged; noindex is not used as access control.

These are crawler directives, not a guarantee against indexing, screenshots, link sharing or bots that ignore them. The site remains public, as requested. Existing search listings can take time to disappear after recrawl. Changes apply to the AWS application, not the separate original holiday-sale store or legacy browser-local Sites prototype.

Reference: https://developers.google.com/search/docs/crawling-indexing/block-indexing
