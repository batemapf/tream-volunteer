# Launch checks — November 15, 2026

## Results

| Check | Result |
|---|---|
| 300 board reads over 10 seconds | Passed; isolated handler plus real separate DynamoDB table. p95 60 ms, max 233 ms. Does not include Lambda/API Gateway. |
| 50 simultaneous claims for last five spaces | Exactly five booked; 45 returned full. Final attendance 10/10, no duplicate roster IDs. p95 1.083 seconds. |
| Lost-response replay | Twenty simultaneous replays returned the same single booking ID; one roster entry. |
| 300 queued confirmations, SES mocked | All processed once in three cycles (120 + 120 + 60); 139.8 seconds total. Minimum send gap 287 ms. Real worker pacing, leases, GSI and completion writes used. Real SES latency/delivery not measured; zero real emails sent. |
| Initial production read ramp | Safety stop at 5 requests/sec: seven of eight requests timed out at three seconds; one returned 200 after about three seconds. No higher stage attempted in that run. |
| Warm production ramp | All 350 requests returned 200: 50 at 5/sec, 100 at 10/sec, 200 at 20/sec. Each stage lasted ten seconds with five-second rests. p95 282/259/268 ms; maximum 371 ms. Eight in-flight requests maximum. |

## Startup finding

CloudWatch REPORT entries confirm eight new Lambda execution environments during the initial ramp. First-invocation duration was roughly 2.4–3.0 seconds plus 110–183 ms of reported initialization. Subsequent handler durations were around 50–64 ms. Sequential curl diagnostics measured 113–157 ms end to end. This supports a startup/first-request cost, rather than an HTTP 5xx or sustained steady-state bottleneck. The repeat ramp used the same stop thresholds; they were not loosened to obtain a pass.

The API is configured for 256 MB; lazy AWS SDK/client initialization occurs on the first request. Regional Lambda concurrency remains 10. A higher-memory API configuration should be measured separately to reduce startup cost before a concentrated launch. Warm throughput is not a guarantee for a cold burst of hundreds of users, and the isolated write test does not measure production Lambda write throughput.

## Production safety

- Production traffic was only GET /schedule plus aggregate read-only health checks; no test signup, schedule edit or production record cleanup occurred.
- All synthetic writes used a uniquely named temporary table. The table was deleted and deletion verified before production ramping.
- SES was replaced with a mock for the isolated worker check.
- No deployed infrastructure or application code was changed during these tests.
- Post-check health reported no Lambda errors/throttles, no pending mail and no failed notifications. CloudWatch metrics can lag recent requests; the 350 warm HTTP results are direct observations.

## Evidence

- Isolated checks + cold safety stop: https://github.com/batemapf/tream-volunteer/actions/runs/43730363125
- Sequential timing/CloudWatch diagnosis: https://github.com/batemapf/tream-volunteer/actions/runs/43730850165
- Warm read ramp + startup reports: https://github.com/batemapf/tream-volunteer/actions/runs/43730978156

The manual `Bounded launch load check` workflow supports a full isolated+read-only run, diagnostics-only, or production-read-only mode. A safety-stop run intentionally concludes with failure, preserves aggregate results in the workflow summary, and does not proceed to higher rates.
