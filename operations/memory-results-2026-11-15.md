# Lambda memory comparison — November 15, 2026

The exact deployed API zip was tested in a temporary Lambda against 17 synthetic shifts in a separate DynamoDB table. Its IAM policy allowed only reads from that table and writes to its own logs; it had no production table access or email permission. Tests ran sequentially to consume at most one regional Lambda concurrency slot. Sizes were interleaved, with three verified fresh environments and nine warm requests per size.

| Memory | Median cold init + handler | Cold range | Median direct-invoke wall time, cold | Median warm handler | Median billed compute for cold request |
|---|---:|---:|---:|---:|---:|
| 256 MB | 2,907.94 ms | 2,836.28–2,980.56 ms | 3,053.86 ms | 32.97 ms | 0.727 GB-seconds |
| 512 MB | 1,491.97 ms | 1,454.51–1,548.64 ms | 1,636.60 ms | 14.94 ms | 0.746 GB-seconds |
| 1024 MB | 776.22 ms | 757.09–806.42 ms | 928.51 ms | 13.77 ms | 0.777 GB-seconds |

Recommendation: 1024 MB for the API. Median cold server time fell about 73% relative to 256 MB. 512 MB cut it about 49%, but 1024 MB gives more startup headroom under the regional concurrency quota of 10. This is a small sample of real Lambda invocations, not a proof of simultaneous cold-burst capacity. API Gateway and browser networking are excluded from server timings.

Four times the memory did not mean four times the cold-request compute: billed GB-seconds increased about 7% because duration decreased. Warm-request compute cost increases; no dollar estimate is inferred here.

Production remained at 256 MB and its code hash was verified unchanged. No production write or email was performed. All temporary resources (function, table, log group, inline policy, role) were removed. The post-test health check reported no Lambda errors or throttles and no mail backlog.

Evidence: https://github.com/batemapf/tream-volunteer/actions/runs/43741058856

Applying the recommendation is a separate targeted Terraform change to `aws_lambda_function.api.memory_size`; the restricted deployment guard must explicitly allow that API-only memory change. No mail/feedback memory, schedule migration or signup writes are needed.
