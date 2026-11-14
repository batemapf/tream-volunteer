# Volunteer subdomain migration

Chosen address: https://volunteer.brentholidaysale.com. The base domain remains the existing Shopify storefront. A subdomain lets the AWS application use its own CloudFront/TLS setup without a Shopify application proxy or a reverse proxy in front of store traffic. Shopify can optionally provide a short /volunteer redirect later.

Stage 1 (deployed, run 43628974211): request the CloudFront ACM certificate in us-east-1, generate validation DNS, and prepare origin checks. `enable_site_domain` defaults false while DNS is added. No root/www records are changed. All 46 unit checks and live application checks passed.

GoDaddy additions (CNAME, TTL 30 minutes):

- `_c86f43a0fcdca37f87acd38f86db00d1.volunteer` → `_7523395186e2f878c82d076443e5899f.wzccmgtwzk.acm-validations.aws.`
- `volunteer` → `dy2majdy4ufxo.cloudfront.net`

Keep certificate validation DNS permanently for renewals. The new host will only work after stage 2; existing CloudFront URLs continue working throughout.

Stage 2: verify public DNS and certificate issuance, enable the Terraform site-domain variable, deploy the CloudFront alternate hostname/certificate, and verify HTTPS, noindex, public signup and management flows. API CORS and mutation origin checks allow both exact HTTPS origins. New emails then use the canonical volunteer subdomain, while old CloudFront management links remain valid. Reply-To remains unchanged pending the owner's clarification about Shopify versus volunteer email feedback.

Signup data lives in the same AWS table and does not move. Browser-local My signups shortcuts do not automatically transfer between origins; existing private email links still provide cross-browser management. Organizer sessions also require signing in on the new origin.
