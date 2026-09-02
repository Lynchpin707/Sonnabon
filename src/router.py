"""One routing decision per request.

Tier, risk and rewrite all read the same input, so they cost one round trip
rather than four sequential agents. The model is advisory: a malformed reply
falls back to the heuristic instead of failing the request.
"""

import hashlib
import json
import re
from dataclasses import dataclass, replace

from . import config
from .provider import complete

TIERS = ("cheap", "mid", "heavy", "max")

_FILLER = re.compile(
    r"\b(?:please act as an expert|could you help me draft|thank you in advance"
    r"|agis comme un expert|merci d'avance)\b",
    re.IGNORECASE,
)
_HEAVY = ("strategy", "strategie", "budget", "legal", "contract", "audit", "forecast")
_MID = ("code", "debug", "refactor", "analyse", "analyze", "sql", "schema")
_CHEAP = ("email", "caption", "translate", "reply", "newsletter", "summar",
          "post", "rediger", "redige")

_PROMPT = """Return JSON only, no prose.

{{"tier": "cheap|mid|heavy|max", "domain": "snake_case", "risk": "low|medium|high"}}

cheap: short factual or formulaic work.
mid: code, analysis, drafting that needs care.
heavy: strategy, legal or financial judgement.
max: irreversible decisions where a wrong answer costs real money.

Request:
{text}
"""


@dataclass(frozen=True)
class Decision:
    tier: str
    domain: str
    risk: str
    prompt: str
    cached: bool = False


# Small models need scaffolding that large ones do not. Sending the same words
# to every tier is what makes routing down feel like a downgrade: the model is
# not only weaker, it is also being asked in a way that suits a stronger one.
_ADAPT = {
    "cheap": (
        "Answer the request directly and stop. Short sentences. No preamble, no "
        "restating the question, no closing offer of further help. If the "
        "request has several parts, answer them in order.\n\n"
    ),
    "mid": "",
    "heavy": "",
    "max": (
        "This answer may be acted on and may be difficult to undo. State the "
        "assumptions you are relying on, and say plainly what would change your "
        "answer if it turned out to be false.\n\n"
    ),
}


def adapt(prompt, tier):
    """Prepend the scaffolding that tier needs. Same request, fitted wording."""
    return _ADAPT.get(tier, "") + prompt


def normalise(text):
    return re.sub(r"\s+", " ", _FILLER.sub("", text)).strip()


def heuristic(text):
    """Errors are not symmetric.

    Overrouting wastes fractions of a cent. Underrouting sends reasoning work
    to a model that cannot do it, and the user pays in frustration, which no
    ledger records. So cheap requires positive evidence and mid is the default.
    """
    lowered = text.lower()
    if len(text) > 2000 or any(word in lowered for word in _HEAVY):
        tier = "heavy"
    elif any(word in lowered for word in _MID):
        tier = "mid"
    elif len(text) < 400 and any(word in lowered for word in _CHEAP):
        tier = "cheap"
    else:
        tier = "mid"
    # Never escalates to max. Only an explicit model decision spends top tier
    # money, so a parse failure cannot become an expensive one.
    return Decision(tier, "unclassified", "low", normalise(text))


_cache = {}


def decide(text):
    """Return the decision and the router's own spend, or None if it did not run.

    Identical requests reuse the prior decision, which costs nothing and skips
    a full round trip. Real traffic repeats far more than it looks like it does.
    """
    key = hashlib.sha256(normalise(text).encode()).hexdigest()
    if key in _cache:
        return replace(_cache[key], cached=True), None

    decision = heuristic(text)
    completion = None

    if len(text) >= config.ROUTER_MIN_CHARS:
        completion = complete(
            config.MODELS["cheap"], _PROMPT.format(text=text), max_tokens=64
        )
        decision = _parse(completion.text, text) or decision

    if len(_cache) > 1000:
        _cache.clear()
    _cache[key] = decision
    return decision, completion


def _parse(raw, text):
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if not match:
        return None
    try:
        data = json.loads(match.group())
    except json.JSONDecodeError:
        return None
    if data.get("tier") not in TIERS:
        return None
    return Decision(
        data["tier"],
        str(data.get("domain") or "unclassified"),
        str(data.get("risk") or "low"),
        normalise(text),
    )
