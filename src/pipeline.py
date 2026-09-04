"""Runs one request from start to finish.

Read this file first. It is the whole system, and every other module is one of
the steps it calls.

There is one entry point, not two. Both lanes below are Strands agents, so the
ledger, the budget cap and the approval gate are enforced by the same hooks
whichever one runs. The only thing the lane decides is how many heads look at
the problem: one agent for formulaic work, a case officer and four specialists
for work that needs judgement.

An earlier version had a second, agent-free path for speed. It was faster
because it was doing less than anyone believed, and nothing that path did was
recorded the same way.
"""

import hashlib
import uuid
from dataclasses import dataclass, replace

from . import agents, bureau, config, memory, provider, router

RATING_RATE = 0.05
COMMENT_RATE = 0.01


@dataclass(frozen=True)
class Result:
    text: str
    decision: router.Decision
    record: memory.Record | None
    case_id: str = ""
    path: str = "solo"
    calls: tuple = ()
    blocks: tuple = ()
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


def classify(text, user, tier=None):
    """What this request is, and what it should cost to answer.

    A tier passed in is the person overriding on purpose, so no classification
    happens and no history is consulted.
    """
    if tier:
        return router.Decision(tier, "override", "low", text), None

    decision, completion = router.decide(text)
    raised = memory.escalate(decision.tier, memory.prior(user, decision.domain))
    return replace(decision, tier=raised), completion


def should_shadow(request_id):
    """Whether to pay to measure the counterfactual on this one."""
    return _bucket(request_id, "shadow") < config.SHADOW_RATE


def measure_baseline(text, decision):
    """Run the same request on the habit tier and see what it really costs.

    Deliberately not through an agent and not inside the case file: this is
    measurement spend, not the user's work, and folding it into their bill
    would make the ledger claim they were charged for a control.

    Inline rather than backgrounded, because the sampled request is the one
    request whose ledger row has to be complete. It is a few percent of
    traffic, and those few wait twice.
    """
    model = config.MODELS[config.HABIT_TIER]
    try:
        completion = provider.complete(model, router.adapt(text, config.HABIT_TIER))
    except Exception:
        # A failed control is not a failed request. Record nothing and let the
        # answer the person actually asked for go out.
        return None
    return (memory.price(config.PRICED[config.HABIT_TIER], completion),
            completion.output_tokens)


def run(text, user="demo", approve=None, tier=None, watch=None, case_id=None):
    """One turn of one case, start to finish.

    A case is a conversation, not a single question. Pass the case_id back to
    continue it and the agent sees what was already said; leave it out and a
    new case is opened. ``watch`` is called with each step as it happens, so an
    interface can show the work while it is being done rather than after.
    """
    request_id = uuid.uuid4().hex
    case_id = case_id or uuid.uuid4().hex
    decision, router_completion = classify(text, user, tier)

    # The same rule the agent team uses, from the same function. Two entry
    # points that disagree about what needs permission is how a gate gets
    # bypassed without anybody deciding to bypass it.
    if bureau.needs_approval(decision) and not (approve and approve(decision)):
        return Result("", decision, None, case_id=case_id, approved=False)

    case = bureau.CaseFile(user=user, authorised=config.runnable(decision.tier),
                           watch=watch)
    token = bureau.open_case(case)
    try:
        if router.needs_team(decision):
            answer, path = agents.team(text, user, case_id), "team"
        else:
            answer, path = agents.solo(text, decision, case_id), "solo"
        adapted = router.adapt(text, decision.tier) != text
    finally:
        bureau.close_case(token)

    shadow = (measure_baseline(text, decision)
              if should_shadow(request_id) else None)

    record = memory.save(memory.build_case(
        request_id, user, decision, case, router_completion, case_id, adapted,
        shadow))
    return Result(
        answer,
        decision,
        record,
        case_id=case_id,
        path=path,
        calls=tuple(case.calls),
        blocks=tuple(case.blocks),
        ask_rating=should_rate(request_id),
        ask_comment=should_comment(request_id),
    )
