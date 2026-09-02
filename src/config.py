"""Model catalogue and runtime settings.

Costs are USD per 1M tokens. Bedrock is priced separately from the Anthropic
first-party API, so confirm every figure here against the AWS pricing page
before it appears in the pitch.
"""

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Model:
    id: str
    input_cost: float
    output_cost: float


USE_AWS = os.getenv("USE_AWS", "false").lower() == "true"
AWS_REGION = os.getenv("AWS_REGION", "us-east-1")

# Hackathon ladder. Deliberately not the newest models: these are cheap,
# broadly enabled on Bedrock, and a 50 dollar budget covers heavy testing.
# Confirm all three against the AWS Bedrock pricing page, which is priced
# separately from the Anthropic first party API.
BEDROCK = {
    "cheap": Model("amazon.nova-micro-v1:0", 0.035, 0.14),
    "mid": Model("anthropic.claude-haiku-4-5", 1.00, 5.00),
    "heavy": Model("anthropic.claude-sonnet-5", 2.00, 10.00),
    "max": Model("anthropic.claude-fable-5", 10.00, 50.00),
}

OLLAMA = {
    "cheap": Model("qwen2.5:1.5b", 0.0, 0.0),
    "mid": Model("qwen2.5:3b", 0.0, 0.0),
    "heavy": Model("qwen2.5:3b", 0.0, 0.0),
    "max": Model("qwen2.5:3b", 0.0, 0.0),
}

MODELS = BEDROCK if USE_AWS else OLLAMA

# What you run against, versus what you cost. Local development is free, but
# every economic figure must price the models a client actually pays for, or
# the whole savings model quietly reports zero.
PRICED = BEDROCK

# The router pays output rates to save input rates. Under this length it can
# never recover its own cost, so the deterministic heuristic decides instead.
ROUTER_MIN_CHARS = int(os.getenv("ROUTER_MIN_CHARS", "400"))

MAX_OUTPUT_TOKENS = int(os.getenv("MAX_OUTPUT_TOKENS", "1024"))
LEDGER_PATH = os.getenv("LEDGER_PATH", "ledger.jsonl")


# The highest tier we can afford to actually call. Routing still decides the
# true tier and the ledger still records what it would have cost, but execution
# is clamped to this. A student budget changes what we run, not what we measure.
CEILING = os.getenv("TIER_CEILING", "mid")

TIER_ORDER = tuple(PRICED)


def runnable(tier):
    """Clamp a routing decision down to the tier the budget allows."""
    return TIER_ORDER[min(TIER_ORDER.index(tier), TIER_ORDER.index(CEILING))]
