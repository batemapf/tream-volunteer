"""Reject resource creation/deletion and unrelated infrastructure changes."""

import json
import sys

allowed = {
    "aws_lambda_function.api",
    "aws_lambda_function.mail",
    "aws_lambda_function.feedback",
    "aws_apigatewayv2_stage.api",
    "aws_cognito_user_pool_client.organizers",
}
plan = json.load(open(sys.argv[1]))
changes = [
    r
    for r in plan.get("resource_changes", [])
    if r["change"]["actions"] not in (["no-op"], ["read"])
]
for resource in plan.get("resource_changes", []):
    change = resource["change"]
    if change["actions"] in (["no-op"], ["read"]):
        continue
    assert (
        resource["address"] in allowed
    ), f"Unexpected resource change: {resource['address']}"
    assert change["actions"] == ["update"], "Only in-place updates are allowed"
    before, after = change["before"], change["after"]
    if resource["type"] == "aws_cognito_user_pool_client":
        assert resource["address"] == "aws_cognito_user_pool_client.organizers"
        assert len(changes) == 1, "Session rollout must be the only resource change"
        assert (
            before["access_token_validity"] == 15
            and after["access_token_validity"] == 720
        )
        assert before["id_token_validity"] == 15 and after["id_token_validity"] == 720
        for key in set(before) | set(after):
            if key not in (
                "access_token_validity",
                "id_token_validity",
                "last_modified_date",
            ):
                assert before.get(key) == after.get(
                    key
                ), f"Unexpected auth change: {key}"
    elif resource["type"] == "aws_lambda_function":
        for key in (
            "environment",
            "role",
            "function_name",
            "reserved_concurrent_executions",
            "runtime",
            "handler",
        ):
            assert before.get(key) == after.get(
                key
            ), f"Unexpected Lambda setting: {key}"
        if before.get("memory_size") != after.get("memory_size"):
            assert (
                resource["address"] == "aws_lambda_function.api"
            ), "Only API memory may change"
            assert before["memory_size"] == 256 and after["memory_size"] == 1024
            assert len(changes) == 1, "Memory rollout must be the only resource change"
            for key in (
                "source_code_hash",
                "timeout",
                "architectures",
                "layers",
                "vpc_config",
                "tracing_config",
            ):
                assert before.get(key) == after.get(
                    key
                ), f"Unexpected change during memory rollout: {key}"
        else:
            assert before.get("memory_size") == after.get("memory_size")
        assert after["timeout"] == (
            50 if resource["name"] == "mail" else before["timeout"]
        )
    else:
        assert after["default_route_settings"][0]["throttling_burst_limit"] == 25
        assert after["default_route_settings"][0]["throttling_rate_limit"] == 25
    print(f"Allowed in-place update: {resource['address']}")
print("Guard passed: no database, IAM, domain, deletion or replacement changes.")
