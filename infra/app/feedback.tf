resource "aws_sesv2_configuration_set" "mail" {
  configuration_set_name = local.name
  reputation_options { reputation_metrics_enabled = true }
  suppression_options { suppressed_reasons = ["BOUNCE", "COMPLAINT"] }
}
resource "aws_sesv2_configuration_set_event_destination" "feedback" {
  configuration_set_name = aws_sesv2_configuration_set.mail.configuration_set_name
  event_destination_name = "tream-feedback"
  event_destination {
    enabled              = true
    matching_event_types = ["BOUNCE", "COMPLAINT", "DELIVERY", "REJECT", "DELIVERY_DELAY", "RENDERING_FAILURE"]
    event_bridge_destination {
      event_bus_arn = "arn:aws:events:us-east-2:${data.aws_caller_identity.current.account_id}:event-bus/default"
    }
  }
}
resource "aws_sqs_queue" "feedback_failures" {
  name                      = "${local.name}-feedback-failures"
  message_retention_seconds = 1209600
  sqs_managed_sse_enabled   = true
}
resource "aws_cloudwatch_event_rule" "feedback" {
  name = "${local.name}-feedback"
  event_pattern = jsonencode({
    source = ["aws.ses"]
    detail = { mail = { tags = { "ses:configuration-set" = [aws_sesv2_configuration_set.mail.configuration_set_name] } } }
  })
}
resource "aws_sqs_queue_policy" "feedback_failures" {
  queue_url = aws_sqs_queue.feedback_failures.url
  policy    = jsonencode({ Version = "2012-10-17", Statement = [{ Effect = "Allow", Principal = { Service = "events.amazonaws.com" }, Action = "sqs:SendMessage", Resource = aws_sqs_queue.feedback_failures.arn, Condition = { ArnEquals = { "aws:SourceArn" = aws_cloudwatch_event_rule.feedback.arn } } }] })
}
resource "aws_iam_role" "feedback" {
  name                 = "tream-runtime-dev-feedback"
  permissions_boundary = "arn:aws:iam::${data.aws_caller_identity.current.account_id}:policy/tream-runtime-boundary"
  assume_role_policy   = jsonencode({ Version = "2012-10-17", Statement = [{ Effect = "Allow", Principal = { Service = "lambda.amazonaws.com" }, Action = "sts:AssumeRole" }] })
}
resource "aws_cloudwatch_log_group" "feedback" {
  name              = "/aws/lambda/${local.name}-feedback"
  retention_in_days = 14
}
resource "aws_iam_role_policy" "feedback" {
  name = "tream-mail-feedback"
  role = aws_iam_role.feedback.id
  policy = jsonencode({ Version = "2012-10-17", Statement = [
    { Effect = "Allow", Action = ["dynamodb:PutItem", "dynamodb:UpdateItem"], Resource = aws_dynamodb_table.data.arn },
    { Effect = "Allow", Action = ["sqs:SendMessage"], Resource = aws_sqs_queue.feedback_failures.arn },
    { Effect = "Allow", Action = ["logs:CreateLogStream", "logs:PutLogEvents"], Resource = "${aws_cloudwatch_log_group.feedback.arn}:*" }
  ] })
}
resource "aws_lambda_function" "feedback" {
  function_name    = "${local.name}-feedback"
  role             = aws_iam_role.feedback.arn
  handler          = "feedback.handler"
  runtime          = "python3.13"
  filename         = data.archive_file.api.output_path
  source_code_hash = data.archive_file.api.output_base64sha256
  memory_size      = 256
  timeout          = 25
  environment {
    variables = { TABLE_NAME = aws_dynamodb_table.data.name, EMAIL_CONFIGURATION_SET = aws_sesv2_configuration_set.mail.configuration_set_name }
  }
  depends_on = [aws_iam_role_policy.feedback]
}
resource "aws_lambda_permission" "feedback" {
  statement_id  = "AllowSESFeedbackRule"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.feedback.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.feedback.arn
}
resource "aws_lambda_function_event_invoke_config" "feedback" {
  function_name                = aws_lambda_function.feedback.function_name
  maximum_retry_attempts       = 2
  maximum_event_age_in_seconds = 3600
  destination_config {
    on_failure { destination = aws_sqs_queue.feedback_failures.arn }
  }
}
resource "aws_cloudwatch_event_target" "feedback" {
  rule = aws_cloudwatch_event_rule.feedback.name
  arn  = aws_lambda_function.feedback.arn
  dead_letter_config { arn = aws_sqs_queue.feedback_failures.arn }
  retry_policy {
    maximum_event_age_in_seconds = 3600
    maximum_retry_attempts       = 10
  }
  depends_on = [aws_sqs_queue_policy.feedback_failures, aws_lambda_permission.feedback]
}
resource "aws_cloudwatch_metric_alarm" "feedback_failures" {
  alarm_name          = "${local.name}-feedback-failures"
  namespace           = "AWS/SQS"
  metric_name         = "ApproximateNumberOfMessagesVisible"
  dimensions          = { QueueName = aws_sqs_queue.feedback_failures.name }
  statistic           = "Maximum"
  period              = 60
  evaluation_periods  = 1
  threshold           = 0
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = aws_sns_topic.operations[*].arn
  ok_actions          = aws_sns_topic.operations[*].arn
}
resource "aws_cloudwatch_metric_alarm" "feedback_errors" {
  alarm_name          = "${local.name}-feedback-errors"
  namespace           = "AWS/Lambda"
  metric_name         = "Errors"
  dimensions          = { FunctionName = aws_lambda_function.feedback.function_name }
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 0
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = aws_sns_topic.operations[*].arn
  ok_actions          = aws_sns_topic.operations[*].arn
}
# The sale domain uses structured feedback instead of forwarded bounce emails.
# Leave the shared Gmail identity's existing forwarding behavior untouched.
resource "aws_sesv2_email_identity_feedback_attributes" "holiday_sale" {
  email_identity           = aws_sesv2_email_identity.holiday_sale.email_identity
  email_forwarding_enabled = false
  depends_on               = [aws_sesv2_configuration_set_event_destination.feedback]
}
