"""Bounded launch checks: isolated DynamoDB writes; production GET /schedule only."""

import argparse
import copy
import json
import math
import os
import secrets
import sys
import threading
import time
import urllib.error
import urllib.request
import uuid
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from unittest.mock import patch

import boto3
from botocore.config import Config

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from domain import epoch, retention_expiry
from store import DynamoStore
from service import BookingService
import handler
import mail

RESULT = Path(os.environ.get("LOAD_RESULT_FILE", "/tmp/tream-load-results.json"))
TABLE = os.environ["LOAD_TABLE_NAME"]
assert TABLE.startswith("tream-load-") and TABLE != "tream-dev-data"
RESULTS = {}


def record(name, result):
    RESULTS[name] = result
    RESULT.write_text(json.dumps(RESULTS, indent=2))
    print(json.dumps({"check": name, **result}), flush=True)


def percentile(values, percent):
    return (
        round(sorted(values)[max(0, math.ceil(len(values) * percent) - 1)], 3)
        if values
        else 0
    )


def stats(values):
    return {
        "requests": len(values),
        "p50Seconds": percentile(values, 0.5),
        "p95Seconds": percentile(values, 0.95),
        "maxSeconds": round(max(values, default=0), 3),
    }


def fixture(id, capacity=10):
    return {
        "pk": "SHIFT#" + id,
        "id": id,
        "date": "2026-12-05",
        "name": "Isolated load fixture",
        "start": 9,
        "end": 13,
        "capacity": capacity,
        "flex": True,
        "attendance": {"incrementMinutes": 30, "minMinutes": 30},
        "overflowPercent": 0,
        "revision": 0,
        "roster": [],
        "open": True,
        "location": "Test only",
        "startAt": epoch("2026-12-05", 9),
        "endAt": epoch("2026-12-05", 13),
        "publicUntil": epoch("2026-12-07", 0),
        "expiresAt": retention_expiry(epoch("2026-12-06", 19)),
    }


def selection(shift):
    return {
        "shiftId": shift,
        "start": 9,
        "end": 11,
        "name": "Isolated Test Volunteer",
        "phone": "2025550123",
        "shareName": False,
        "idempotencyKey": str(uuid.uuid4()),
        "participantId": str(uuid.uuid4()),
        "manageToken": secrets.token_urlsafe(32),
    }


def scan(store):
    rows, cursor = [], None
    while True:
        args = {"TableName": TABLE, "ConsistentRead": True}
        if cursor:
            args["ExclusiveStartKey"] = cursor
        page = store.client.scan(**args)
        rows.extend(store.decode(row) for row in page.get("Items", []))
        cursor = page.get("LastEvaluatedKey")
        if not cursor:
            return rows


def isolated():
    os.environ.update(
        TABLE_NAME=TABLE,
        SITE_ORIGIN="https://load.invalid",
        EMAIL_ENABLED="true",
        EMAIL_DELIVERY_MODE="test",
        EMAIL_TEST_RECIPIENTS="load-test@example.com",
        EMAIL_FROM="volunteers@brentholidaysale.com",
        EMAIL_REPLY_TO="batemapf@gmail.com",
        EMAIL_CONFIGURATION_SET="tream-dev",
    )
    store = DynamoStore()
    store.client = boto3.client(
        "dynamodb",
        config=Config(
            max_pool_connections=80, retries={"max_attempts": 3, "mode": "standard"}
        ),
    )
    assert store.table == TABLE
    store.client.create_table(
        TableName=TABLE,
        BillingMode="PAY_PER_REQUEST",
        KeySchema=[{"AttributeName": "pk", "KeyType": "HASH"}],
        AttributeDefinitions=[
            {"AttributeName": "pk", "AttributeType": "S"},
            {"AttributeName": "recordType", "AttributeType": "S"},
            {"AttributeName": "createdAt", "AttributeType": "N"},
        ],
        GlobalSecondaryIndexes=[
            {
                "IndexName": "recordType-createdAt",
                "KeySchema": [
                    {"AttributeName": "recordType", "KeyType": "HASH"},
                    {"AttributeName": "createdAt", "KeyType": "RANGE"},
                ],
                "Projection": {"ProjectionType": "ALL"},
            }
        ],
        Tags=[{"Key": "Purpose", "Value": "temporary-launch-load-check"}],
    )
    store.client.get_waiter("table_exists").wait(
        TableName=TABLE, WaiterConfig={"Delay": 2, "MaxAttempts": 90}
    )
    handler._store = store
    service = BookingService(store)
    shifts = [fixture(str(i), 10) for i in range(17)]
    for row in shifts + [{"pk": "EVENT#2026", "shiftIds": [s["id"] for s in shifts]}]:
        store.client.put_item(TableName=TABLE, Item=store.encode(row))

    def read():
        start = time.perf_counter()
        response = handler.handler(
            {"requestContext": {"http": {"method": "GET"}}, "rawPath": "/schedule"},
            None,
        )
        assert response["statusCode"] == 200
        assert len(json.loads(response["body"])["shifts"]) == 17
        return time.perf_counter() - start

    times = []
    start = time.monotonic()
    with ThreadPoolExecutor(max_workers=40) as pool:
        pending = []
        for i in range(300):
            time.sleep(max(0, start + i / 30 - time.monotonic()))
            pending.append(pool.submit(read))
        times = [f.result() for f in pending]
    record(
        "isolated_board_300_over_10_seconds",
        {
            **stats(times),
            "passed": True,
            "scope": "same Python handler plus real isolated DynamoDB; excludes API Gateway and Lambda",
        },
    )

    hot = fixture("hot", 10)
    hot["roster"] = [
        {
            "id": "existing-" + str(i),
            "start": 9,
            "end": 11,
            "publicName": "Volunteer (name private)",
        }
        for i in range(5)
    ]
    store.client.put_item(TableName=TABLE, Item=store.encode(hot))
    gate = threading.Barrier(50)

    def claim(raw):
        gate.wait(timeout=30)
        start = time.perf_counter()
        result = service.batch("load-test@example.com", [raw])["results"][0]
        return result, time.perf_counter() - start

    submitted = [selection("hot") for _ in range(50)]
    with ThreadPoolExecutor(max_workers=50) as pool:
        outcomes = list(pool.map(claim, submitted))
    booked = [r for r, _ in outcomes if r["status"] == "booked"]
    roster = store.get("SHIFT#hot")["roster"]
    assert len(booked) == 5 and len(roster) == 10
    assert len({p["id"] for p in roster}) == 10
    codes = Counter(r.get("code", r["status"]) for r, _ in outcomes)
    assert set(codes) <= {"booked", "full", "retry"}
    record(
        "isolated_50_claim_last_5_spaces",
        {
            **stats([t for _, t in outcomes]),
            "outcomes": dict(codes),
            "newBookings": len(booked),
            "finalAttendance": len(roster),
            "capacity": 10,
            "passed": True,
        },
    )

    retry_shift = fixture("retry", 50)
    store.client.put_item(TableName=TABLE, Item=store.encode(retry_shift))
    raw = selection("retry")
    original = service.book(
        "load-test@example.com", raw
    )  # Pretend the response never reached the browser.
    with ThreadPoolExecutor(max_workers=20) as pool:
        replayed = list(
            pool.map(lambda _: service.book("load-test@example.com", raw), range(20))
        )
    assert {r["bookingId"] for r in replayed} == {original["bookingId"]}
    assert len(store.get("SHIFT#retry")["roster"]) == 1
    record(
        "isolated_dropped_response_20_retries",
        {"replays": 20, "uniqueBookings": 1, "passed": True},
    )

    # Only this test table is ever cleared. Production tables are never used by isolated writes.
    for row in scan(store):
        if row["pk"].startswith("MAIL#"):
            store.client.delete_item(
                TableName=TABLE, Key=store.encode({"pk": row["pk"]})
            )
    for i in range(300):
        booking = {
            "id": "queue-" + str(i),
            "email": "load-test@example.com",
            "name": "Isolated Test",
            "start": 9,
            "end": 11,
            "expiresAt": int(time.time()) + 3600,
        }
        row = mail.notification(booking, retry_shift, "confirmation", "x" * 43)
        store.client.put_item(TableName=TABLE, Item=store.encode(row))
    # Keep the real pacing, leases, query and completion writes. Replace only SES delivery.
    sends = []

    class FakeSES:
        def send_email(self, **kwargs):
            assert kwargs["Destination"]["ToAddresses"] == ["load-test@example.com"]
            sends.append(time.monotonic())
            return {"MessageId": "mock-" + str(len(sends))}

    real_client = boto3.client

    def client(name, *args, **kwargs):
        return FakeSES() if name == "sesv2" else real_client(name, *args, **kwargs)

    cycles = []
    began = time.monotonic()
    time.sleep(2)  # Allow sparse GSI convergence after seeding.
    with patch("boto3.client", side_effect=client):
        for cycle in range(5):
            tick = time.monotonic()
            result = mail.handler({}, None)
            remaining = sum(r.get("recordType") == "mailPending" for r in scan(store))
            cycles.append(
                {
                    "cycle": cycle + 1,
                    "sent": result["sent"],
                    "remaining": remaining,
                    "durationSeconds": round(time.monotonic() - tick, 2),
                }
            )
            print(json.dumps({"mockEmailProgress": cycles[-1]}), flush=True)
            if not remaining:
                break
            time.sleep(max(0, 60 - (time.monotonic() - tick)))
    receipts = [r for r in scan(store) if r["pk"].startswith("MAIL#")]
    assert len(sends) == 300 and len(receipts) == 300
    assert all(r.get("status") == "sent" and "manageToken" not in r for r in receipts)
    assert len({r["messageId"] for r in receipts}) == 300
    gaps = [b - a for a, b in zip(sends, sends[1:])]
    assert min(gaps) >= 0.19
    record(
        "isolated_300_mock_emails",
        {
            "sent": len(sends),
            "elapsedSeconds": round(time.monotonic() - began, 2),
            "cycles": cycles,
            "minimumSendGapSeconds": round(min(gaps), 3),
            "realEmailsSent": 0,
            "passed": True,
        },
    )


def production():
    # The sole production request in this file: GET the public schedule, never POST.
    url = "https://saocxbe6xa.execute-api.us-east-2.amazonaws.com/schedule"
    stop = threading.Event()
    stages, baseline = [], None

    def read():
        start = time.perf_counter()
        status, valid = 0, False
        try:
            req = urllib.request.Request(
                url,
                method="GET",
                headers={"User-Agent": "Tream-bounded-read-only-launch-check"},
            )
            with urllib.request.urlopen(req, timeout=3) as response:
                status = response.status
                valid = isinstance(json.load(response).get("shifts"), list)
        except urllib.error.HTTPError as error:
            status = error.code
        except Exception:
            pass
        duration = time.perf_counter() - start
        if status != 200 or not valid or duration > 2:
            stop.set()
        return status, duration, valid

    for rate in (5, 10, 20):
        started, completed = time.monotonic(), []
        with ThreadPoolExecutor(max_workers=8) as pool:
            pending = []
            for i in range(rate * 10):
                time.sleep(max(0, started + i / rate - time.monotonic()))
                if stop.is_set():
                    break
                if sum(not f.done() for f in pending) >= 8:
                    stop.set()
                    break
                pending.append(pool.submit(read))
            completed = [f.result() for f in pending]
        durations = [t for _, t, _ in completed]
        summary = {
            "ratePerSecond": rate,
            **stats(durations),
            "statuses": dict(Counter(str(s) for s, _, _ in completed)),
            "earlyStop": stop.is_set(),
        }
        if baseline is None:
            baseline = summary["p95Seconds"]
        elif summary["p95Seconds"] > max(0.75, baseline * 2.5):
            stop.set()
            summary["earlyStop"] = True
        stages.append(summary)
        record(
            "production_read_only_ramp",
            {
                "stages": stages,
                "passed": not stop.is_set(),
                "productionWrites": 0,
                "maxInFlight": 8,
            },
        )
        if stop.is_set():
            raise RuntimeError(
                "Read-only ramp stopped at safety threshold; do not increase traffic"
            )
        time.sleep(5)  # Short rest between stages.


def diagnostics():
    from datetime import datetime, timedelta, timezone
    import subprocess

    timings = []
    for _ in range(3):
        result = subprocess.run(
            [
                "curl",
                "--silent",
                "--show-error",
                "--output",
                "/dev/null",
                "--connect-timeout",
                "5",
                "--max-time",
                "10",
                "--write-out",
                '{"status":%{http_code},"dns":%{time_namelookup},"connect":%{time_connect},"tls":%{time_appconnect},"firstByte":%{time_starttransfer},"total":%{time_total}}',
                "https://saocxbe6xa.execute-api.us-east-2.amazonaws.com/schedule",
            ],
            capture_output=True,
            text=True,
        )
        timings.append(
            {
                "exitCode": result.returncode,
                "timing": result.stdout,
                "error": result.stderr[:250],
            }
        )
        time.sleep(1)
    metrics = []
    cw = boto3.client("cloudwatch")
    for namespace, name, dims, statistic in [
        (
            "AWS/Lambda",
            "Duration",
            [{"Name": "FunctionName", "Value": "tream-dev-api"}],
            ["Average", "Maximum"],
        ),
        (
            "AWS/Lambda",
            "ConcurrentExecutions",
            [{"Name": "FunctionName", "Value": "tream-dev-api"}],
            ["Maximum"],
        ),
        (
            "AWS/Lambda",
            "Throttles",
            [{"Name": "FunctionName", "Value": "tream-dev-api"}],
            ["Sum"],
        ),
        (
            "AWS/ApiGateway",
            "Latency",
            [
                {"Name": "ApiId", "Value": "saocxbe6xa"},
                {"Name": "Stage", "Value": "$default"},
            ],
            ["Average", "Maximum"],
        ),
        (
            "AWS/ApiGateway",
            "IntegrationLatency",
            [
                {"Name": "ApiId", "Value": "saocxbe6xa"},
                {"Name": "Stage", "Value": "$default"},
            ],
            ["Average", "Maximum"],
        ),
        (
            "AWS/ApiGateway",
            "5xx",
            [
                {"Name": "ApiId", "Value": "saocxbe6xa"},
                {"Name": "Stage", "Value": "$default"},
            ],
            ["Sum"],
        ),
    ]:
        points = cw.get_metric_statistics(
            Namespace=namespace,
            MetricName=name,
            Dimensions=dims,
            StartTime=datetime.now(timezone.utc) - timedelta(minutes=15),
            EndTime=datetime.now(timezone.utc),
            Period=60,
            Statistics=statistic,
        )["Datapoints"]
        metrics.append(
            {
                "namespace": namespace,
                "metric": name,
                "points": [
                    {k: str(v) if k == "Timestamp" else v for k, v in row.items()}
                    for row in points
                ],
            }
        )
    reports = (
        boto3.client("logs")
        .filter_log_events(
            logGroupName="/aws/lambda/tream-dev-api",
            startTime=int((time.time() - 900) * 1000),
            filterPattern='"REPORT RequestId"',
            limit=100,
        )
        .get("events", [])
    )
    report_messages = [row["message"] for row in reports]
    print(json.dumps({"lambdaTimingReports": report_messages}), flush=True)
    record(
        "production_read_diagnostics",
        {"sequentialCurl": timings, "recentMetrics": metrics},
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "mode", choices=["isolated", "production", "cleanup", "diagnostics"]
    )
    args = parser.parse_args()
    if RESULT.exists():
        RESULTS.update(json.loads(RESULT.read_text()))
    if args.mode == "cleanup":
        client = boto3.client("dynamodb")
        try:
            client.delete_table(TableName=TABLE)
            client.get_waiter("table_not_exists").wait(
                TableName=TABLE, WaiterConfig={"Delay": 2, "MaxAttempts": 90}
            )
            print("Temporary isolated table removed.", flush=True)
        except client.exceptions.ResourceNotFoundException:
            print("Temporary isolated table already absent.", flush=True)
    else:
        globals()[args.mode]()
