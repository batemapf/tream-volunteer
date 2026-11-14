# CloudFront certificates must be in Northern Virginia, even with an Ohio backend.
provider "aws" {
  alias  = "certificates"
  region = "us-east-1"
  default_tags {
    tags = { Project = "tream", Environment = "development", ManagedBy = "Terraform" }
  }
}
variable "enable_site_domain" {
  type        = bool
  default     = false
  description = "Activate after ACM's DNS validation record has been added in GoDaddy."
}
locals {
  site_domain = "volunteer.brentholidaysale.com"
}
resource "aws_acm_certificate" "site" {
  provider          = aws.certificates
  domain_name       = local.site_domain
  validation_method = "DNS"
  lifecycle { create_before_destroy = true }
}
resource "aws_acm_certificate_validation" "site" {
  count                   = var.enable_site_domain ? 1 : 0
  provider                = aws.certificates
  certificate_arn         = aws_acm_certificate.site.arn
  validation_record_fqdns = [for option in aws_acm_certificate.site.domain_validation_options : option.resource_record_name]
}
output "site_domain_dns" {
  description = "GoDaddy records for the chosen volunteer subdomain."
  value = {
    validation = [for option in aws_acm_certificate.site.domain_validation_options : {
      type  = option.resource_record_type
      name  = trimsuffix(option.resource_record_name, ".brentholidaysale.com.")
      value = option.resource_record_value
    }]
    site    = { type = "CNAME", name = "volunteer", value = aws_cloudfront_distribution.web.domain_name }
    enabled = var.enable_site_domain
  }
}
output "legacy_site_url" { value = local.cloudfront_origin }
