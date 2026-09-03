"""Configuration the owner can change without editing code.

Overlays the defaults in config.py and persists to settings.json beside the
ledger. Model ids and prices live here because anyone running this will want to
point it at their own models, and their own negotiated rates, without a
redeploy.

Credentials are deliberately not here. AWS keys come from the standard
credential chain, and a web form is the wrong place to type a secret.
"""

import json
import os
from pathlib import Path

from . import config

PATH = Path(os.getenv("SETTINGS_PATH", "settings.json"))

# Everything the interface is allowed to change, and nothing else.
FIELDS = ("backend", "region", "tiers", "ceiling", "habit", "case_budget",
          "router_min_chars", "max_output_tokens", "domain_rules")


def defaults():
    return {
        "backend": "bedrock" if config.USE_AWS else "ollama",
        "region": config.AWS_REGION,
        "tiers": {
            tier: {"id": config.PRICED[tier].id,
                   "input_cost": config.PRICED[tier].input_cost,
                   "output_cost": config.PRICED[tier].output_cost}
            for tier in config.TIER_ORDER
        },
        "ceiling": config.CEILING,
        "habit": config.HABIT_TIER,
        "case_budget": 0.25,
        "router_min_chars": config.ROUTER_MIN_CHARS,
        "max_output_tokens": config.MAX_OUTPUT_TOKENS,
        # Domain to tier, set by hand. An entry here beats the classifier,
        # because somebody who knows their own work beats a guess about it.
        "domain_rules": {},
    }


def load():
    current = defaults()
    try:
        saved = json.loads(PATH.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return current
    for key in FIELDS:
        if key in saved:
            current[key] = saved[key]
    return current


def save(patch):
    """Merge a change, validate it, write it, and make it take effect now."""
    current = load()
    for key in FIELDS:
        if key in patch:
            current[key] = patch[key]
    validate(current)
    PATH.write_text(json.dumps(current, indent=2), encoding="utf-8")
    apply(current)
    return current


def validate(values):
    """Reject a bad setting at the boundary. A ceiling of 'enromous' must fail
    here, where the message can say so, not four calls later inside a hook."""
    for name in ("ceiling", "habit"):
        if values[name] not in config.TIER_ORDER:
            raise ValueError(f"{name} must be one of {config.TIER_ORDER}")
    for tier, model in values["tiers"].items():
        if tier not in config.TIER_ORDER:
            raise ValueError(f"{tier} is not a tier")
        if not str(model.get("id", "")).strip():
            raise ValueError(f"{tier} needs a model id")
        for cost in ("input_cost", "output_cost"):
            if float(model[cost]) < 0:
                raise ValueError(f"{tier} {cost} cannot be negative")
    for domain, tier in values["domain_rules"].items():
        if tier not in config.TIER_ORDER:
            raise ValueError(f"rule for {domain} names an unknown tier {tier}")
    if float(values["case_budget"]) <= 0:
        raise ValueError("case budget must be more than zero")


def apply(values=None):
    """Push settings into the running process.

    One function writes these globals, so there is one place to look when a
    number on screen disagrees with a number in the ledger.
    """
    values = values or load()
    priced = {
        tier: config.Model(spec["id"], float(spec["input_cost"]),
                           float(spec["output_cost"]))
        for tier, spec in values["tiers"].items()
    }
    config.USE_AWS = values["backend"] == "bedrock"
    config.AWS_REGION = values["region"]
    config.PRICED = priced
    config.MODELS = priced if config.USE_AWS else config.OLLAMA
    config.CEILING = values["ceiling"]
    config.HABIT_TIER = values["habit"]
    config.ROUTER_MIN_CHARS = int(values["router_min_chars"])
    config.MAX_OUTPUT_TOKENS = int(values["max_output_tokens"])
    config.DOMAIN_RULES = dict(values["domain_rules"])

    from . import bureau

    bureau.CASE_BUDGET = float(values["case_budget"])
    return values
