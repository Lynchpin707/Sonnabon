"""One routing decision per request, before any agent is built.

Tier, domain and risk come from the same input in a single cheap call, and the
result decides both which model answers and whether the full team is worth it.
The model is advisory: a malformed reply falls back to the keyword heuristic
rather than failing the request, and it may route down but never talk down a
risk the heuristic flagged.
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
# Prefixes, matched at a word boundary. Plain substring matching sent every
# request containing "transcript" to the code tier, because "script" is inside
# it, and missed "prices" because the list said "pricing".
_HEAVY = ("strateg", "budget", "legal", "contract", "agreement", "audit",
          "forecast", "negotiat", "negocia", "pric", "margin", "valuation",
          "tax", "complian", "dispute", "redline", "clause", "runway",
          "acquisition", "term sheet")
_MID = ("code", "debug", "refactor", "analy", "sql", "schema", "spreadsheet",
        "formula", "script", "quer", "calculat", "webhook", "endpoint",
        "integration", "pipeline", "regex", "dashboard")
_CHEAP = ("email", "caption", "translat", "repl", "newsletter", "summar",
          "post", "rediger", "redige", "thank", "remind", "invite", "recap",
          "changelog")


def _hits(words, text):
    """Prefix match at a word boundary, so transcript is not a script."""
    return re.search(r"\b(?:" + "|".join(words) + ")", text, re.IGNORECASE)

# Work you cannot take back. Deliberately narrow: every term here stops the
# request and asks the owner, so a loose list turns the gate into noise and
# people learn to click through it.
_RISK = re.compile(
    r"\b(?:terminat"
    r"|end (?:our|the) (?:\w+ ){0,3}(?:relationship|contract|agreement)"
    r"|cancel the (?:contract|order|agreement|subscription)"
    r"|break the (?:contract|lease)"
    r"|sue\b|lawsuit|litigat"
    r"|sign (?:the|this|off on)"
    r"|wire (?:the )?(?:funds|money)"
    r"|acquire the|merge with"
    r"|lay(?:ing)? off|let(?:ting)? .{0,40}?\bgo\b"
    r"|make .{0,20}?redundant|redundanc"
    r"|dismiss|resign|dissolve|liquidat|breach of"
    r"|pull the plug|shut (?:it|us|them) down)",
    re.IGNORECASE)

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

    Risk is read here rather than assumed. It used to be the literal string
    "low" on every request, which quietly made the approval gate and the agent
    team unreachable: both of them key off it.
    """
    if len(text) > 2000 or _hits(_HEAVY, text):
        tier = "heavy"
    elif _hits(_MID, text):
        tier = "mid"
    elif len(text) < 400 and _hits(_CHEAP, text):
        tier = "cheap"
    else:
        tier = "mid"
    risk = "high" if _RISK.search(text) else "low"
    # Never escalates to max. Only an explicit model decision spends top tier
    # money, so a parse failure cannot become an expensive one.
    return Decision(tier, "unclassified", risk, normalise(text))


def apply_rules(decision):
    """A tier the owner pinned to a domain beats the classifier.

    Applied after the cache, never before, so changing a rule takes effect on
    the next request instead of whenever the cache happens to turn over.
    """
    tier = config.DOMAIN_RULES.get(decision.domain)
    return replace(decision, tier=tier) if tier in TIERS else decision


def needs_team(decision):
    """Whether this request is worth the full agent team.

    The team costs about six model calls; a solo agent costs one. That is a
    latency decision as much as a cost one, so the system makes it rather than
    the person waiting. Judgement work earns the team; formulaic work does not.

    Both lanes are Strands agents either way, so the ledger, the budget cap and
    the approval gate are the same whichever runs. This only decides how many
    heads look at the problem.
    """
    return decision.risk == "high" or decision.tier in ("heavy", "max")


_cache = {}


def decide(text):
    """Return the decision and the router's own spend, or None if it did not run.

    Identical requests reuse the prior decision, which costs nothing and skips
    a full round trip. Real traffic repeats far more than it looks like it does.
    """
    key = hashlib.sha256(normalise(text).encode()).hexdigest()
    if key in _cache:
        return apply_rules(replace(_cache[key], cached=True)), None

    decision = heuristic(text)
    completion = None

    if len(text) >= config.ROUTER_MIN_CHARS:
        completion = complete(
            config.MODELS["cheap"], _PROMPT.format(text=text), max_tokens=64
        )
        parsed = _parse(completion.text, text)
        if parsed:
            # A model may route the tier down, which is the whole point. It may
            # not talk down a risk the deterministic rule already flagged. The
            # keyword list is narrow on purpose, and whether an action can be
            # undone is not a matter of opinion.
            decision = replace(parsed, risk="high")                 if decision.risk == "high" else parsed

    if len(_cache) > 1000:
        _cache.clear()
    _cache[key] = decision
    return apply_rules(decision), completion


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
