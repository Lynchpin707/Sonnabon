"""Sonnabon as an Amazon Bedrock AgentCore Runtime agent.

The web app runs the agent on one machine. This file is the same agent packaged
for AgentCore Runtime: one entrypoint, the same runs, the same eighteen tools
and the same hooks. Nothing about the agent changes between the two.

Deploy with the AgentCore starter toolkit, from the repository root:

    pip install "sonnabon[aws]"
    agentcore configure --entrypoint src/bakery/cloud/agentcore_app.py
    agentcore launch

Payloads it accepts:

    {"kind": "nightly"}                          close of trade, sent by the schedule
    {"kind": "weekly"}                           the weekly review
    {"kind": "noticed"}                          what stood out today
    {"kind": "asked", "prompt": "how is today?"} a question from the owner

On AgentCore the model is Amazon Bedrock, resolved by agent/model.py from the
runtime's IAM role. This was not deployed during the hackathon because neither
team account could get Bedrock model access.
"""

import os
import sys

# Run as a file by the AgentCore container, so make the repository importable.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))))))

from src.bakery.agent import runs  # noqa: E402

KINDS = ("nightly", "weekly", "noticed", "asked")


def handle(payload):
    """Validate one invocation and run it. Always returns a JSON-safe dict."""
    if not isinstance(payload, dict):
        return {"ok": False, "error": "The payload must be a JSON object.",
                "example": {"kind": "nightly"}}

    kind = payload.get("kind", "nightly")
    prompt = payload.get("prompt")

    if kind not in KINDS:
        return {"ok": False, "error": f"{kind!r} is not a run.",
                "kinds": list(KINDS)}
    if kind == "asked" and not (isinstance(prompt, str) and prompt.strip()):
        return {"ok": False, "error": "An asked run needs a prompt.",
                "example": {"kind": "asked", "prompt": "How is today going?"}}

    try:
        result = runs.with_agent(kind, prompt=prompt)
    except Exception as error:
        # Reported, not raised: a scheduled run that fails should say why in
        # its response instead of disappearing into a retry.
        return {"ok": False, "kind": kind, "error": str(error)}
    return {"ok": True, **result}


try:
    from bedrock_agentcore.runtime import BedrockAgentCoreApp
except ImportError:                          # the aws extra is not installed
    BedrockAgentCoreApp = None

app = BedrockAgentCoreApp() if BedrockAgentCoreApp else None

if app is not None:
    @app.entrypoint
    def invoke(payload):
        return handle(payload)


if __name__ == "__main__":
    if app is None:
        sys.exit('The AgentCore SDK is not installed. Run: pip install "sonnabon[aws]"')
    app.run()
