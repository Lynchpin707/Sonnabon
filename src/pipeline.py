"""Runs one request from start to finish.

Read this file first. It is the whole system in forty lines, and every other
module is one of the steps it calls.

It is a plain function, not an agent, because the order never changes.
"""

import hashlib
import uuid
from dataclasses import dataclass, replace

from . import config, memory, provider, router

RATING_RATE = 0.05
COMMENT_RATE = 0.01


@dataclass(frozen=True)
class Result:
    text: str
    decision: router.Decision
    record: memory.Record | None
    approved: bool = True
    ask_rating: bool = False
    ask_comment: bool = False


def _bucket(request_id, salt):
    digest = hashlib.sha256(f"{salt}:{request_id}".encode()).digest()
    return int.from_bytes(digest[:8], "big") / 2**64


def should_rate(request_id):
    """Sampled, not asked every time. Constant prompting trains people to lie.

    Deterministic on the request id so a demo replays identically.
    """
    return _bucket(request_id, "rate") < RATING_RATE


def should_comment(request_id):
    return should_rate(request_id) and _bucket(request_id, "comment") < COMMENT_RATE


def run(text, user="demo", approve=None):
    request_id = uuid.uuid4().hex
    decision, router_completion = router.decide(text)

    tier = memory.escalate(decision.tier, memory.prior(user, decision.domain))
    decision = replace(decision, tier=tier)

    if approve and decision.risk == "high" and not approve(decision):
        return Result("", decision, None, approved=False)

    ran = config.runnable(tier)
    completion = provider.complete(config.MODELS[ran], decision.prompt)

    record = memory.save(
        memory.build(request_id, user, decision, ran, router_completion, completion)
    )
    return Result(
        completion.text,
        decision,
        record,
        ask_rating=should_rate(request_id),
        ask_comment=should_comment(request_id),
    )
