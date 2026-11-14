# Test-only sender and recipient are verified SES email identities. No DNS needed.
resource "aws_iam_role" "mail" {
  name                 = "tream-runtime-dev-mail"
  permissions_boundary = "arn:aws:iam::${data.aws_caller_identity.current.account_id}:policy/tream-runtime-boundary"
  assume_role_policy   = jsonencode({ Version = "2012-10-17", Statement = [{ Effect = "Allow", Principal = { Service = "lambda.amazonaws.com" }, Action = "sts:AssumeRole" }] })
}
resource "aws_cloudwatch_log_group" "mail" {
  name              = "/aws/lambda/${local.name}-mail"
  retention_in_days = 14
}
resource "aws_iam_role_policy" "mail" {
  name = "tream-mail-test-delivery"
  role = aws_iam_role.mail.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      { Effect = "Allow", Action = ["dynamodb:Query"], Resource = "${aws_dynamodb_table.data.arn}/index/recordType-createdAt" },
      { Effect = "Allow", Action = ["dynamodb:UpdateItem"], Resource = aws_dynamodb_table.data.arn },
      { Effect = "Allow", Action = ["ses:SendEmail"], Resource = "arn:aws:ses:us-east-2:${data.aws_caller_identity.current.account_id}:identity/batemapf@gmail.com", Condition = { StringEquals = { "ses:FromAddress" = "batemapf@gmail.com" }, "ForAllValues:StringEquals" = { "ses:Recipients" = ["batemapf@gmail.com"] } } },
      { Effect = "Allow", Action = ["logs:CreateLogStream", "logs:PutLogEvents"], Resource = "${aws_cloudwatch_log_group.mail.arn}:*" }
    ]
  })
}
resource "aws_lambda_function" "mail" {
  function_name                  = "${local.name}-mail"
  role                           = aws_iam_role.mail.arn
  handler                        = "mail.handler"
  runtime                        = "python3.13"
  filename                       = data.archive_file.api.output_path
  source_code_hash               = data.archive_file.api.output_base64sha256
  memory_size                    = 256
  timeout                        = 25
  reserved_concurrent_executions = 1
  environment {
    variables = { TABLE_NAME = aws_dynamodb_table.data.name, SITE_ORIGIN = local.origin, EMAIL_ENABLED = "true", EMAIL_FROM = "batemapf@gmail.com", EMAIL_REPLY_TO = "batemapf@gmail.com", EMAIL_TEST_RECIPIENTS = "batemapf@gmail.com" }
  }
  depends_on = [aws_iam_role_policy.mail]
}
resource "aws_cloudwatch_event_rule" "mail" {
  name                = "${local.name}-mail"
  schedule_expression = "rate(1 minute)"
}
resource "aws_cloudwatch_event_target" "mail" {
  rule = aws_cloudwatch_event_rule.mail.name
  arn  = aws_lambda_function.mail.arn
}
resource "aws_lambda_permission" "mail" {
  statement_id  = "AllowMailSchedule"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.mail.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.mail.arn
}
