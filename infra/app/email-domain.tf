# Domain authentication only. Runtime sending remains restricted to the Gmail test identity.
resource "aws_sesv2_email_identity" "holiday_sale" {
  email_identity = "brentholidaysale.com"
}
resource "aws_sesv2_email_identity_mail_from_attributes" "holiday_sale" {
  email_identity         = aws_sesv2_email_identity.holiday_sale.email_identity
  mail_from_domain       = "bounce.brentholidaysale.com"
  behavior_on_mx_failure = "USE_DEFAULT_VALUE"
}
output "email_dns_records" {
  description = "GoDaddy DNS additions; these do not change the website or root mail routing."
  value = concat([
    for token in aws_sesv2_email_identity.holiday_sale.dkim_signing_attributes[0].tokens : {
      type = "CNAME", name = "${token}._domainkey", value = "${token}.dkim.amazonses.com"
    }
    ], [
    { type = "MX", name = "bounce", value = "feedback-smtp.us-east-2.amazonses.com", priority = 10 },
    { type = "TXT", name = "bounce", value = "v=spf1 include:amazonses.com ~all" },
    { type = "TXT", name = "_dmarc", value = "v=DMARC1; p=none;" }
  ])
}
