# Operational alerts use SNS independently of SES and the booking mail worker.
resource "aws_sns_topic" "operations" {
  name = "${local.name}-operations"
}
resource "aws_sns_topic_policy" "operations" {
  arn = aws_sns_topic.operations.arn
  policy = jsonencode({ Version = "2012-10-17", Statement = [{
    Sid       = "CloudWatchAlarms", Effect = "Allow", Principal = { Service = "cloudwatch.amazonaws.com" }, Action = "sns:Publish", Resource = aws_sns_topic.operations.arn,
    Condition = { StringEquals = { "aws:SourceAccount" = data.aws_caller_identity.current.account_id }, ArnLike = { "aws:SourceArn" = "arn:aws:cloudwatch:us-east-2:${data.aws_caller_identity.current.account_id}:alarm:tream-*" } }
  }] })
}
resource "aws_sns_topic_subscription" "operations" {
  topic_arn = aws_sns_topic.operations.arn
  protocol  = "email"
  endpoint  = "batemapf@gmail.com"
}
resource "aws_cloudwatch_log_metric_filter" "mail_delivery_failures" {
  name           = "${local.name}-mail-delivery-failures"
  log_group_name = aws_cloudwatch_log_group.mail.name
  pattern        = "{ $.event = \"mail_delivery_failed\" }"
  metric_transformation {
    name          = "MailDeliveryFailures"
    namespace     = "Tream"
    value         = "1"
    default_value = "0"
  }
}
resource "aws_cloudwatch_metric_alarm" "mail_delivery_failures" {
  alarm_name          = "${local.name}-mail-delivery-failures"
  alarm_description   = "Booking notification exhausted delivery retries. Review the private mail receipt and worker logs; the booking itself remains valid."
  namespace           = "Tream"
  metric_name         = aws_cloudwatch_log_metric_filter.mail_delivery_failures.metric_transformation[0].name
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 0
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.operations.arn]
  ok_actions          = [aws_sns_topic.operations.arn]
}
resource "aws_cloudwatch_metric_alarm" "mail_worker_errors" {
  alarm_name          = "${local.name}-mail-worker-errors"
  alarm_description   = "Booking mail worker crashed. Review Lambda logs; pending notifications remain in the private outbox."
  namespace           = "AWS/Lambda"
  metric_name         = "Errors"
  dimensions          = { FunctionName = aws_lambda_function.mail.function_name }
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 0
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.operations.arn]
  ok_actions          = [aws_sns_topic.operations.arn]
}
output "operations_alert_topic" { value = aws_sns_topic.operations.arn }
