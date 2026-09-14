"""Wake the agent at closing time with Amazon EventBridge Scheduler.

The schedule calls the AgentCore Runtime directly through a Scheduler universal
target, the bedrock-agentcore InvokeAgentRuntime action, so there is no Lambda
in between.

One thing to know before trusting the console: Scheduler waits about thirty
seconds for a universal target. A run that takes longer can be reported as
failed even when it finished. Give the schedule a dead-letter queue, and treat
the agent's own journal as the record of whether a night actually ran.

Usage, after the agent is deployed on AgentCore:

    sonnabon-schedule --runtime-arn arn:aws:bedrock-agentcore:... \\
                      --role-arn arn:aws:iam::...:role/sonnabon-scheduler

The role needs bedrock-agentcore:InvokeAgentRuntime on that runtime. The
parameter names inside the target input follow the InvokeAgentRuntime API
reference; confirm them on the first deploy.
"""

import argparse
import json

TARGET_ARN = "arn:aws:scheduler:::aws-sdk:bedrockagentcore:invokeAgentRuntime"

# Close of trade is 19:30 and the shop is shut on Mondays, so the nightly run
# fires five minutes after closing, Tuesday to Sunday.
NIGHTLY = "35 19 ? * TUE-SUN *"
WEEKLY = "0 21 ? * SUN *"


def request(name, runtime_arn, role_arn, cron, timezone, kind):
    """The CreateSchedule request, built separately so it can be checked."""
    if not runtime_arn.startswith("arn:"):
        raise ValueError(f"{runtime_arn!r} is not an ARN.")
    if not role_arn.startswith("arn:"):
        raise ValueError(f"{role_arn!r} is not an ARN.")
    return {
        "Name": name,
        "ScheduleExpression": f"cron({cron})",
        "ScheduleExpressionTimezone": timezone,
        "FlexibleTimeWindow": {"Mode": "OFF"},
        "Target": {
            "Arn": TARGET_ARN,
            "RoleArn": role_arn,
            "Input": json.dumps({
                "agentRuntimeArn": runtime_arn,
                "payload": json.dumps({"kind": kind}),
            }),
        },
    }


def create(runtime_arn, role_arn, timezone="Europe/Paris", weekly=True,
           client=None):
    """Create the nightly schedule, and the weekly one unless told not to."""
    if client is None:
        import boto3
        client = boto3.client("scheduler")
    made = [client.create_schedule(**request(
        "sonnabon-nightly", runtime_arn, role_arn, NIGHTLY, timezone, "nightly"))]
    if weekly:
        made.append(client.create_schedule(**request(
            "sonnabon-weekly", runtime_arn, role_arn, WEEKLY, timezone, "weekly")))
    return made


def main():
    parser = argparse.ArgumentParser(
        description="Wake Sonnabon on AgentCore at closing time.")
    parser.add_argument("--runtime-arn", required=True)
    parser.add_argument("--role-arn", required=True)
    parser.add_argument("--timezone", default="Europe/Paris")
    parser.add_argument("--no-weekly", action="store_true")
    args = parser.parse_args()
    for made in create(args.runtime_arn, args.role_arn, args.timezone,
                       weekly=not args.no_weekly):
        print(made.get("ScheduleArn", made))


if __name__ == "__main__":
    main()
