"""Reject resource creation/deletion and unrelated infrastructure changes."""

import json
import sys

allowed = {
    "aws_lambda_function.api",
    "aws_lambda_function.mail",
    "aws_lambda_function.feedback",
    "aws_apigatewayv2_stage.api",
}
plan = json.load(open(sys.argv[1]))
for resource in plan.get("resource_changes", []):
    change = resource["change"]
    if change["actions"] in (["no-op"], ["read"]):
        continue
    assert (
        resource["address"] in allowed
    ), f"Unexpected resource change: {resource['address']}"
    assert change["actions"] == ["update"], "Only in-place updates are allowed"
    before, after = change["before"], change["after"]
    if resource["type"] == "aws_lambda_function":
        for key in (
            "environment",
            "role",
            "function_name",
            "reserved_concurrent_executions",
            "memory_size",
            "runtime",
            "handler",
        ):
            assert before.get(key) == after.get(
                key
            ), f"Unexpected Lambda setting: {key}"
        assert after["timeout"] == (
            50 if resource["name"] == "mail" else before["timeout"]
        )
    else:
        assert after["default_route_settings"][0]["throttling_burst_limit"] == 25
        assert after["default_route_settings"][0]["throttling_rate_limit"] == 25
    print(f"Allowed in-place update: {resource['address']}")
print("Guard passed: no database, IAM, domain, deletion or replacement changes.")
