# Transactional email options

Evaluated November 12, 2026. Recommendation: Amazon SES, subject to production-access approval and region-specific limits.

| Option | Fit | Main tradeoff |
| --- | --- | --- |
| Amazon SES | Best fit for the selected AWS stack, IAM integration and low seasonal volume | More setup: region-specific identity verification, production access, event handling and monitoring |
| Resend | Alternative if a simpler email developer experience becomes more valuable than AWS consolidation | Separate service/account and plan limits; domain authentication is still required |
| Postmark | Alternative when delivery tooling/support is worth a separate provider | Separate billing and service configuration; domain authentication is still required |

SES pay-as-you-go base outbound pricing is currently $0.10 per 1,000 emails, with data/add-ons and other AWS services separate. Thus 10,000 emails would have a $1 base send charge, not a $1 total hosting/operations estimate. Check current regional pricing and choose the actual plan at setup; no dedicated IP is recommended for this low-volume event.

GoDaddy DNS access is confirmed. Select a sender domain/subdomain, verify the SES identity in the chosen region, and add provider-issued Easy DKIM records. Configure aligned custom MAIL FROM/SPF if used, and DMARC carefully without disrupting existing mail. Use a monitored Reply-To; SES outbound delivery does not create an inbox. Request SES production access early: sandbox restrictions prevent ordinary sending to unverified recipients, and production quotas vary. Do not assume approval or inbox placement is guaranteed.

Capture delivery/bounce/complaint events, suppress failing recipients, rate-limit outgoing mail and resend requests, and test real Gmail/Outlook/school inboxes before launch. Send email separately per contact. Management links require confirmation before mutations; email scanners must not be able to cancel by following a link.

Sources:
- https://aws.amazon.com/ses/pricing/
- https://docs.aws.amazon.com/ses/latest/dg/request-production-access.html
- https://docs.aws.amazon.com/ses/latest/dg/regions.html
- https://docs.aws.amazon.com/ses/latest/dg/send-email-getting-started-migrate.html
- https://resend.com/pricing
- https://postmarkapp.com/pricing
