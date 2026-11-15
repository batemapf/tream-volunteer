"""Compare real Lambda startup/memory using the deployed zip and an isolated read-only table."""

import argparse
import base64
import hashlib
import json
import os
import re
import statistics
import sys
import time
import urllib.request
from pathlib import Path

import boto3
from botocore.config import Config

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from store import DynamoStore
from domain import epoch

SUFFIX = os.environ["MEMORY_CHECK_ID"]
assert re.fullmatch(r"[0-9]+-[0-9]+", SUFFIX)
FUNCTION = "tream-memory-" + SUFFIX
TABLE = "tream-load-memory-" + SUFFIX
ROLE = "tream-runtime-memory-" + SUFFIX
GROUP = "/aws/lambda/" + FUNCTION
RESULT = Path(os.environ.get("MEMORY_RESULT_FILE", "/tmp/tream-memory-results.json"))
clients = {
    name: boto3.client(
        name, config=Config(read_timeout=60, retries={"total_max_attempts": 1})
    )
    for name in ("lambda", "dynamodb", "iam", "logs", "sts")
}


def cleanup():
    # These names can only identify this run's temporary resources, never production.
    for client, method, args in [
        (clients["lambda"], "delete_function", {"FunctionName": FUNCTION}),
        (clients["logs"], "delete_log_group", {"logGroupName": GROUP}),
        (clients["dynamodb"], "delete_table", {"TableName": TABLE}),
        (
            clients["iam"],
            "delete_role_policy",
            {"RoleName": ROLE, "PolicyName": "isolated-read-only"},
        ),
        (clients["iam"], "delete_role", {"RoleName": ROLE}),
    ]:
        try:
            getattr(client, method)(**args)
            print("Removed temporary resource: " + method, flush=True)
        except Exception as error:
            if getattr(error, "response", {}).get("Error", {}).get("Code") not in (
                "ResourceNotFoundException",
                "NoSuchEntity",
                "NoSuchEntityException",
            ):
                raise
    clients["dynamodb"].get_waiter("table_not_exists").wait(
        TableName=TABLE, WaiterConfig={"Delay": 2, "MaxAttempts": 90}
    )
    print(
        "Temporary function, table, log group and IAM role cleanup complete.",
        flush=True,
    )


def run():
    live = clients["lambda"].get_function(FunctionName="tream-dev-api")
    config = live["Configuration"]
    assert (
        config["MemorySize"] == 256
    ), "Unexpected live memory baseline; inspect before testing"
    with urllib.request.urlopen(live["Code"]["Location"], timeout=30) as response:
        code = response.read()
    assert (
        base64.b64encode(hashlib.sha256(code).digest()).decode() == config["CodeSha256"]
    )
    account = clients["sts"].get_caller_identity()["Account"]
    table_arn = f"arn:aws:dynamodb:us-east-2:{account}:table/{TABLE}"
    clients["dynamodb"].create_table(
        TableName=TABLE,
        BillingMode="PAY_PER_REQUEST",
        KeySchema=[{"AttributeName": "pk", "KeyType": "HASH"}],
        AttributeDefinitions=[{"AttributeName": "pk", "AttributeType": "S"}],
        Tags=[{"Key": "Purpose", "Value": "temporary-memory-comparison"}],
    )
    clients["dynamodb"].get_waiter("table_exists").wait(
        TableName=TABLE, WaiterConfig={"Delay": 2, "MaxAttempts": 90}
    )
    os.environ["TABLE_NAME"] = TABLE
    store = DynamoStore()
    for i in range(17):
        row = {
            "pk": "SHIFT#" + str(i),
            "id": str(i),
            "date": "2026-12-05",
            "name": "Isolated memory fixture",
            "start": 9,
            "end": 13,
            "capacity": 30,
            "flex": True,
            "open": True,
            "roster": [],
            "revision": 0,
            "overflowPercent": 0,
            "attendance": {"incrementMinutes": 30, "minMinutes": 30},
            "startAt": epoch("2026-12-05", 9),
            "endAt": epoch("2026-12-05", 13),
            "publicUntil": epoch("2026-12-07", 0),
            "expiresAt": epoch("2026-12-07", 0),
        }
        clients["dynamodb"].put_item(TableName=TABLE, Item=store.encode(row))
    clients["dynamodb"].put_item(
        TableName=TABLE,
        Item=store.encode(
            {"pk": "EVENT#2026", "shiftIds": [str(i) for i in range(17)]}
        ),
    )
    role = clients["iam"].create_role(
        RoleName=ROLE,
        PermissionsBoundary=f"arn:aws:iam::{account}:policy/tream-runtime-boundary",
        AssumeRolePolicyDocument=json.dumps(
            {
                "Version": "2012-10-17",
                "Statement": [
                    {
                        "Effect": "Allow",
                        "Principal": {"Service": "lambda.amazonaws.com"},
                        "Action": "sts:AssumeRole",
                    }
                ],
            }
        ),
    )["Role"]
    clients["iam"].put_role_policy(
        RoleName=ROLE,
        PolicyName="isolated-read-only",
        PolicyDocument=json.dumps(
            {
                "Version": "2012-10-17",
                "Statement": [
                    {
                        "Effect": "Allow",
                        "Action": ["dynamodb:GetItem", "dynamodb:BatchGetItem"],
                        "Resource": table_arn,
                    },
                    {
                        "Effect": "Allow",
                        "Action": ["logs:CreateLogStream", "logs:PutLogEvents"],
                        "Resource": f"arn:aws:logs:us-east-2:{account}:log-group:{GROUP}:*",
                    },
                ],
            }
        ),
    )
    clients["logs"].create_log_group(logGroupName=GROUP)
    environment = {
        "TABLE_NAME": TABLE,
        "SITE_ORIGIN": "https://memory.invalid",
        "EMAIL_ENABLED": "false",
        "MEMORY_SAMPLE": "initial",
    }
    # IAM propagation can take a few seconds. Retrying creation never invokes the function.
    for attempt in range(12):
        try:
            clients["lambda"].create_function(
                FunctionName=FUNCTION,
                Runtime=config["Runtime"],
                Role=role["Arn"],
                Handler=config["Handler"],
                Code={"ZipFile": code},
                Timeout=config["Timeout"],
                MemorySize=256,
                Architectures=config.get("Architectures", ["x86_64"]),
                Environment={"Variables": environment},
            )
            break
        except Exception as error:
            if "cannot be assumed" not in str(error) or attempt == 11:
                raise
            time.sleep(5)
    clients["lambda"].get_waiter("function_active_v2").wait(
        FunctionName=FUNCTION, WaiterConfig={"Delay": 2, "MaxAttempts": 90}
    )
    payload = json.dumps(
        {"requestContext": {"http": {"method": "GET"}}, "rawPath": "/schedule"}
    ).encode()

    def invoke(cold):
        began = time.perf_counter()
        response = clients["lambda"].invoke(
            FunctionName=FUNCTION,
            InvocationType="RequestResponse",
            LogType="Tail",
            Payload=payload,
        )
        wall = (time.perf_counter() - began) * 1000
        body = json.loads(response["Payload"].read())
        assert not response.get("FunctionError"), "Isolated function error"
        assert (
            body["statusCode"] == 200 and len(json.loads(body["body"])["shifts"]) == 17
        )
        log = base64.b64decode(response["LogResult"]).decode()
        report = next(
            line for line in log.splitlines() if line.startswith("REPORT RequestId")
        )
        duration = float(re.search(r"\bDuration: ([0-9.]+) ms", report).group(1))
        init = re.search(r"Init Duration: ([0-9.]+) ms", report)
        billed = float(re.search(r"Billed Duration: ([0-9.]+) ms", report).group(1))
        if cold:
            assert (
                init
            ), "Expected a fresh environment; do not count a warm request as cold"
        return {
            "handlerMs": duration,
            "initMs": float(init.group(1)) if init else 0,
            "serverTotalMs": round(duration + (float(init.group(1)) if init else 0), 2),
            "invokeWallMs": round(wall, 2),
            "billedMs": billed,
        }

    trials = []
    # Interleave sizes to avoid attributing time/order effects to memory.
    for index, memory in enumerate([256, 512, 1024, 1024, 256, 512, 512, 1024, 256]):
        clients["lambda"].update_function_configuration(
            FunctionName=FUNCTION,
            MemorySize=memory,
            Environment={"Variables": {**environment, "MEMORY_SAMPLE": str(index)}},
        )
        clients["lambda"].get_waiter("function_updated_v2").wait(
            FunctionName=FUNCTION, WaiterConfig={"Delay": 2, "MaxAttempts": 90}
        )
        trial = {
            "memoryMB": memory,
            "cold": invoke(True),
            "warm": [invoke(False) for _ in range(3)],
        }
        trials.append(trial)
        RESULT.write_text(json.dumps({"trials": trials}, indent=2))
        print(json.dumps({"memoryTrial": trial}), flush=True)
    summaries = []
    for memory in (256, 512, 1024):
        group = [t for t in trials if t["memoryMB"] == memory]
        cold = [t["cold"]["serverTotalMs"] for t in group]
        warm = [w["serverTotalMs"] for t in group for w in t["warm"]]
        summaries.append(
            {
                "memoryMB": memory,
                "coldSamples": len(cold),
                "coldMedianMs": round(statistics.median(cold), 2),
                "coldMinMs": min(cold),
                "coldMaxMs": max(cold),
                "warmMedianMs": round(statistics.median(warm), 2),
                "coldMedianGBSeconds": round(
                    statistics.median(
                        [t["cold"]["billedMs"] / 1000 * memory / 1024 for t in group]
                    ),
                    4,
                ),
            }
        )
    # Explicitly verify that the production setting/code did not change during this test.
    after = clients["lambda"].get_function_configuration(FunctionName="tream-dev-api")
    assert (
        after["MemorySize"] == config["MemorySize"]
        and after["CodeSha256"] == config["CodeSha256"]
    )
    result = {
        "summaries": summaries,
        "trials": trials,
        "productionUnchanged": True,
        "source": "exact deployed API zip; separate read-only fixture table; direct sequential Lambda invokes",
        "productionMemoryMB": after["MemorySize"],
        "realEmailsSent": 0,
    }
    RESULT.write_text(json.dumps(result, indent=2))
    print(
        json.dumps({"memorySummary": summaries, "productionUnchanged": True}),
        flush=True,
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=["run", "cleanup"])
    args = parser.parse_args()
    globals()[args.mode]()
