"""The forensics agent.

The one agent in TBI, and the only place an agent belongs. It runs over the
ledger on a schedule rather than inside a request, so it adds no latency to
anything a person is waiting for.

It decides for itself what to look at and when to stop looking, which is the
part a function cannot do. Routing is a classification and stays a function.

Its standing instruction is to say nothing unless something needs a decision.
"""

from strands import Agent, tool

from . import config, memory

SYSTEM = """You are the forensics agent at the Tokens Bureau of Investigation.

You review one person's model spending and report only what they need to act
on. You work for them, not for the bill.

You have tools that read the record: what they spent and on which tier, how
they rated the answers they got, and which weeks look unlike their others. Use
as many as you need and stop when you can answer.

What is worth reporting:
  A tier they keep rating badly. They are paying for answers they reject.
  A tier they rate well that costs many times what a cheaper one would.
  A week whose spending does not look like their other weeks, with the reason.

What is not worth reporting:
  Small changes. Normal variation. Anything you would not interrupt someone for.
  Restating the totals back to them. They can already see totals.

If nothing meets that bar, reply with exactly: NOTHING TO REPORT.

Otherwise write at most four sentences. Say what you found, what it cost them,
and what you would change. Plain language, no jargon, no preamble. A person
running a small business is reading this between two other things."""


@tool
def spending(user: str) -> str:
    """Total spend and request count for this user, broken down by model tier."""
    rows = memory.history(user)
    if not rows:
        return "no requests recorded"

    tiers = {}
    for row in rows:
        entry = tiers.setdefault(row.tier, {"n": 0, "spend": 0.0})
        entry["n"] += 1
        entry["spend"] += row.total_cost

    lines = [f"{len(rows)} requests, {sum(r.total_cost for r in rows):.4f} USD total"]
    lines += [
        f"  {tier}: {v['n']} requests, {v['spend']:.4f} USD"
        for tier, v in sorted(tiers.items())
    ]
    return "\n".join(lines)


@tool
def satisfaction() -> str:
    """Mean rating per tier, where 1 is a good answer and -1 is a bad one."""
    scores = memory.by_tier()
    if not scores:
        return "no ratings collected yet"
    return "\n".join(
        f"{tier}: {s['mean']:+.2f} over {s['n']} ratings" for tier, s in scores.items()
    )


@tool
def unusual() -> str:
    """Users whose most recent request cost several times their own median."""
    flagged = memory.anomalies()
    if not flagged:
        return "nothing unusual"
    return "\n".join(
        f"{user}: {latest:.4f} USD against a median of {median:.4f}"
        for user, latest, median in flagged
    )


@tool
def tier_prices() -> str:
    """What each tier costs per million tokens, so savings can be estimated."""
    return "\n".join(
        f"{tier}: {m.id}, {m.input_cost} in / {m.output_cost} out"
        for tier, m in config.PRICED.items()
    )


def _model():
    if config.USE_AWS:
        from strands.models.bedrock import BedrockModel

        return BedrockModel(
            model_id=config.MODELS["mid"].id, region_name=config.AWS_REGION
        )

    from strands.models.openai import OpenAIModel

    return OpenAIModel(model_id=config.MODELS["mid"].id, stream=False)


def review(user):
    """Run the audit. Returns None when there is nothing worth surfacing."""
    agent = Agent(
        model=_model(),
        system_prompt=SYSTEM,
        tools=[spending, satisfaction, unusual, tier_prices],
    )
    finding = str(agent(f"Review model spending for {user}.")).strip()
    return None if "NOTHING TO REPORT" in finding.upper() else finding
