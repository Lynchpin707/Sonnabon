"""Sonnabon on AWS.

Everything here is dormant on a laptop. Each module switches on only when its
AWS setting is present:

    storage.py        reads the till export from S3 when BILLS_FILE is s3://
    agentcore_app.py  the agent as an Amazon Bedrock AgentCore Runtime entrypoint
    schedule.py       an EventBridge Scheduler rule that wakes it at closing time

Nothing imports boto3 or the AgentCore SDK until one of these is used, so the
local demo and the test suite never need AWS credentials.
"""
