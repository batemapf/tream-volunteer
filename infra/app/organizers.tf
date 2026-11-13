resource "aws_cognito_user_pool" "organizers" {
  name                = "${local.name}-organizers"
  user_pool_tier      = "LITE"
  deletion_protection = "ACTIVE"
  username_configuration { case_sensitive = false }
  admin_create_user_config { allow_admin_create_user_only = true }
  password_policy {
    minimum_length                   = 12
    require_lowercase                = true
    require_uppercase                = true
    require_numbers                  = true
    require_symbols                  = true
    temporary_password_validity_days = 7
  }
  account_recovery_setting {
    recovery_mechanism {
      name     = "admin_only"
      priority = 1
    }
  }
  lifecycle { prevent_destroy = true }
}
resource "aws_cognito_user_pool_client" "organizers" {
  name                          = "${local.name}-organizer-web"
  user_pool_id                  = aws_cognito_user_pool.organizers.id
  generate_secret               = false
  explicit_auth_flows           = ["ALLOW_USER_PASSWORD_AUTH", "ALLOW_REFRESH_TOKEN_AUTH"]
  prevent_user_existence_errors = "ENABLED"
  enable_token_revocation       = true
  access_token_validity         = 15
  id_token_validity             = 15
  refresh_token_validity        = 1
  token_validity_units {
    access_token  = "minutes"
    id_token      = "minutes"
    refresh_token = "days"
  }
}
resource "aws_cognito_user_group" "organizers" {
  name         = "organizers"
  user_pool_id = aws_cognito_user_pool.organizers.id
  description  = "Tream organizers allowed to view private contacts and manage shifts"
}
resource "aws_apigatewayv2_authorizer" "organizers" {
  api_id           = aws_apigatewayv2_api.api.id
  name             = "organizers"
  authorizer_type  = "JWT"
  identity_sources = ["$request.header.Authorization"]
  jwt_configuration {
    audience = [aws_cognito_user_pool_client.organizers.id]
    issuer   = "https://cognito-idp.us-east-2.amazonaws.com/${aws_cognito_user_pool.organizers.id}"
  }
}
resource "aws_apigatewayv2_route" "organizers" {
  for_each           = toset(["GET /admin/{proxy+}", "POST /admin/{proxy+}"])
  api_id             = aws_apigatewayv2_api.api.id
  route_key          = each.value
  authorization_type = "JWT"
  authorizer_id      = aws_apigatewayv2_authorizer.organizers.id
  target             = "integrations/${aws_apigatewayv2_integration.api.id}"
}
output "organizer_url" { value = "${local.origin}/organizer.html" }
output "organizer_pool_id" { value = aws_cognito_user_pool.organizers.id }
output "organizer_client_id" { value = aws_cognito_user_pool_client.organizers.id }
