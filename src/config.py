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

# Bedrock on-demand rates, USD per 1M tokens, checked 2026-09-02.
# Sonnet 5 ran a promotional 2.00/10.00 that ended 2026-08-31, so it is now
# 3.00/15.00. Opus 4.8 is the top tier rather than Fable 5, because Opus is
# confirmed on Bedrock and Fable is not. Confirm in your own console: model
# access on Bedrock is granted per model and is a gate, not a cost.
BEDROCK = {
    "cheap": Model("amazon.nova-micro-v1:0", 0.035, 0.14),
    "mid": Model("anthropic.claude-haiku-4-5", 1.00, 5.00),
    "heavy": Model("anthropic.claude-sonnet-5", 3.00, 15.00),
    "max": Model("anthropic.claude-opus-4-8", 5.00, 25.00),
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

TIER_ORDER = tuple(PRICED)

OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")

# The router pays output rates to save input rates. Under this length it can
# never recover its own cost, so the deterministic heuristic decides instead.
ROUTER_MIN_CHARS = int(os.getenv("ROUTER_MIN_CHARS", "400"))

MAX_OUTPUT_TOKENS = int(os.getenv("MAX_OUTPUT_TOKENS", "1024"))


def _tier(name, default):
    """Reject an unknown tier name loudly. A typo in TIER_CEILING must not
    silently become 'whatever .index() happened to raise on'."""
    if name not in TIER_ORDER:
        raise ValueError(f"{name!r} is not a tier. Use one of {TIER_ORDER}.")
    return name


# The highest tier we can afford to actually call. Routing still decides the
# true tier and the ledger still records what it would have cost, but execution
# is clamped to this. A student budget changes what we run, not what we measure.
CEILING = _tier(os.getenv("TIER_CEILING", "mid"), "mid")

# The tab somebody already had open. Savings are measured against sending the
# same request here, because that is the thing TBI actually replaces. Comparing
# against the clamped tier would only measure our own budget, not the product.
HABIT_TIER = _tier(os.getenv("HABIT_TIER", "heavy"), "heavy")


# Domain to tier, set by hand in the interface. Empty means the classifier
# decides everything. Populated by settings.apply.
DOMAIN_RULES = {}


def runnable(tier):
    """Clamp a routing decision down to the tier the budget allows."""
    return TIER_ORDER[min(TIER_ORDER.index(tier), TIER_ORDER.index(CEILING))]
