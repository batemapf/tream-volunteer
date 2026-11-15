# Launch burst handling — November 15, 2026

Live preflight verified Ohio Lambda concurrency quota 10 (unreserved), API 10 requests/sec with burst 20, SES 14 messages/sec and 50,000/day. No quota changes are made.

- API stage becomes 25 requests/sec, burst 25. This is not a guarantee of Lambda throughput; bounded browser retries smooth temporary 429/502/503/504 responses and network errors.
- Browser retries at most five total attempts, exponential randomized delays capped at ten seconds, using the identical serialized booking body and idempotency key. Reads, booking creation, change and cancellation qualify. Recovery, resend, auth and admin mutations do not auto-retry.
- Mail queries up to 120 queued messages per minute, paces at no more than five SES requests/sec, and stops claiming messages after 40 seconds or with less than six seconds of Lambda time remaining. Lambda timeout is 50 seconds. Global worker lease is 55 seconds; per-message lease remains 90 seconds. Existing retry, suppression and terminal-failure behavior remains intact.
- 120/minute is an upper bound; latency, retries and the time budget reduce actual throughput. Backlog drains over subsequent runs. No exactly-once SES delivery claim is made (an ambiguous SES timeout already has potential for duplicate mail).

Deploy with `workflow_dispatch` input `launch_safe=true`. The commit uses `[skip deploy]` to prevent the normal push deployment. The restricted mode checks the saved Terraform plan for only in-place Lambda/API-stage changes, skips all database migrations and live booking/admin mutation tests, and uploads only the seven affected frontend files without S3 deletion. Request helper is uploaded before dependent scripts and HTML; older cached HTML keeps working through native-fetch fallback.

Local worker tests use fake SES, clocks and DynamoDB; browser checks use intercepted fixtures. No launch-volume test against production is part of this change. Post-deploy operational health is read-only. Mail alarms/inbox subscriptions are not changed.

Original rollback values: API rate 10/burst 20, worker query limit 10/sleep 1.1 seconds, global lease 30 seconds and Lambda timeout 25 seconds. Revert these together if needed; update the plan guard to explicitly allow the original timeout/throttle values before applying a rollback. Do not change worker lease/timeouts independently.
