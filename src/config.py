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

# What runs locally. Nothing here is a requirement: adopt_ollama replaces any
# tier you have not pinned with a model you already have installed. These are
# only what gets suggested when Ollama has nothing at all.
_SUGGESTED = {"cheap": "qwen2.5:1.5b", "mid": "qwen2.5:3b",
              "heavy": "qwen2.5:3b", "max": "qwen2.5:3b"}

# A tier named in the environment is a decision, and decisions are not
# overwritten by discovery.
PINNED = {tier: os.getenv(f"OLLAMA_{tier.upper()}") for tier in _SUGGESTED}

OLLAMA = {tier: Model(PINNED[tier] or name, 0.0, 0.0)
          for tier, name in _SUGGESTED.items()}


def adopt_ollama(installed):
    """Point the unpinned local tiers at models that are actually there.

    ``installed`` is (name, size in bytes), as Ollama reports it. The smallest
    answers the cheap tier and the largest answers the rest: the only agent
    that calls tools runs on mid, and larger models are markedly better at it.

    Returns what each tier ended up on, so the caller can say so. Choosing a
    model on somebody's behalf and not telling them is how a demo ends up
    quietly running on something nobody expected.
    """
    global OLLAMA, MODELS
    if not installed:
        return {tier: model.id for tier, model in OLLAMA.items()}

    by_size = sorted(installed, key=lambda pair: pair[1])
    smallest, largest = by_size[0][0], by_size[-1][0]
    chosen = {"cheap": smallest, "mid": largest, "heavy": largest, "max": largest}

    OLLAMA = {tier: Model(PINNED[tier] or chosen[tier], 0.0, 0.0)
              for tier in _SUGGESTED}
    if not USE_AWS:
        MODELS = OLLAMA
    return {tier: model.id for tier, model in OLLAMA.items()}

MODELS = BEDROCK if USE_AWS else OLLAMA

# What you run against, versus what you cost. Local development is free, but
# every economic figure must price the models a client actually pays for, or
# the whole savings model quietly reports zero.
PRICED = BEDROCK

TIER_ORDER = tuple(PRICED)

OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")

# Where a case keeps its turns. One directory per case, written by Strands.
SESSION_DIR = os.getenv("SESSION_DIR", ".sessions")

# How much of a long case gets summarised away, and how many recent turns stay
# verbatim. Compressing costs a cheap call and saves expensive input tokens on
# every turn after it, which is the whole trade.
SUMMARY_RATIO = float(os.getenv("SUMMARY_RATIO", "0.4"))
KEEP_RECENT_TURNS = int(os.getenv("KEEP_RECENT_TURNS", "6"))

# Length below which the free keyword heuristic decides on its own.
#
# This used to be 400, which saved a fraction of a cent and cost the product
# its two best features: under that length every request came back domain
# "unclassified" and risk "low", so nothing was ever learned per domain and
# neither the approval gate nor the agent team could ever fire. Classifying on
# the cheapest model costs about $0.0001. Set it back above zero if you would
# rather have the fraction of a cent.
ROUTER_MIN_CHARS = int(os.getenv("ROUTER_MIN_CHARS", "0"))

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
#
# heavy rather than mid, so judgement work can run without stopping to ask.
# Only the top tier and genuinely irreversible work need the owner.
CEILING = _tier(os.getenv("TIER_CEILING", "heavy"), "heavy")

# The tab somebody already had open. Savings are measured against sending the
# same request here, because that is the thing TBI actually replaces. Comparing
# against the clamped tier would only measure our own budget, not the product.
#
# The top tier, not the ceiling. Set equal to CEILING it reports zero saving on
# exactly the requests where routing matters most, because the baseline and the
# actual become the same number.
HABIT_TIER = _tier(os.getenv("HABIT_TIER", "max"), "max")


# Domain to tier, set by hand in the interface. Empty means the classifier
# decides everything. Populated by settings.apply.
DOMAIN_RULES = {}


# How often to actually run the request a second time on the habit tier, to
# find out what it would really have cost rather than assuming the token counts
# transfer. Off by default because it spends money to learn something: at two
# percent and top-tier rates it adds well under a cent per hundred requests.
SHADOW_RATE = float(os.getenv("SHADOW_RATE", "0"))


def runnable(tier):
    """Clamp a routing decision down to the tier the budget allows."""
    return TIER_ORDER[min(TIER_ORDER.index(tier), TIER_ORDER.index(CEILING))]
