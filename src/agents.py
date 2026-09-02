"""The agent team.

Four specialists and a supervisor that decides who to call. Each specialist is
its own Strands agent with one job and one system prompt. The supervisor sees
them as tools, which is how a team is assembled in Strands.

Names say the job. Nothing here is called a prosecutor.
"""

import uuid

from strands import Agent, tool

from . import config, forensics, memory, provider, router


def _agent(system_prompt, tier="cheap", tools=None):
    if config.USE_AWS:
        from strands.models.bedrock import BedrockModel

        model = BedrockModel(
            model_id=config.MODELS[tier].id, region_name=config.AWS_REGION
        )
    else:
        from strands.models.openai import OpenAIModel

        model = OpenAIModel(model_id=config.MODELS[tier].id, stream=False)

    return Agent(model=model, system_prompt=system_prompt, tools=tools or [])


SCENARIO = """You read a request and say what it actually is.

Report four things and nothing else:
  intent      what the person wants done, in a few words
  complexity  simple, moderate or hard
  risk        low, medium or high. High means acting on a wrong answer costs
              real money or ends a relationship
  domain      a short snake_case label, chosen from this list only:
              email, copywriting, summary, translation, spreadsheet, coding,
              analysis, negotiation, legal, finance, strategy, other

Use the list exactly. A label you invent cannot be matched against this user's
history later, which silently breaks the routing.

Four lines. No preamble."""

ROUTING = """You choose which model tier answers a request.

  cheap   email, captions, translation, summarising. Formulaic work with a
          known shape and no judgement in it
  mid     code, analysis, spreadsheets. The default when you are unsure
  heavy   strategy, legal, audit, forecasting
  max     decisions that cannot be undone

Mistakes are not symmetric. Sending easy work to a big model wastes a fraction
of a cent. Sending hard work to a small model produces a confident wrong answer
that somebody acts on, and nothing records that cost. So when you are torn,
go up.

You are given the scenario report and what this person thought of answers at
each tier before. A tier they rated badly is not a saving, whatever it cost.

Reply with the tier name and one short sentence of reason. Nothing else."""


@tool
def scenario_agent(request: str) -> str:
    """Read a request and report its intent, complexity, risk and domain."""
    return str(_agent(SCENARIO)(request))


@tool
def routing_agent(scenario_report: str, user: str) -> str:
    """Choose the model tier for a request, using this user's rating history."""
    decision = router.heuristic(scenario_report)
    past = memory.prior(user, decision.domain)
    history = (
        f"prior in this domain: {past['n']} requests, usual tier {past['tier']}, "
        f"mean rating {past['rating']}"
        if past
        else "no history for this user in this domain"
    )
    return str(_agent(ROUTING)(f"{scenario_report}\n\n{history}"))


@tool
def execution_agent(tier: str, request: str, user: str) -> str:
    """Run the request on the chosen tier and record what it really cost."""
    if tier not in config.TIER_ORDER:
        tier = "mid"
    ran = config.runnable(tier)
    completion = provider.complete(config.MODELS[ran], router.adapt(request, tier))
    decision = router.Decision(tier, "unclassified", "low", request)
    record = memory.save(
        memory.build(uuid.uuid4().hex, user, decision, ran, None, completion)
    )
    return (
        f"{completion.text}\n\n"
        f"[{ran}, {record.total_cost:.6f} USD, id {record.request_id[:8]}]"
    )


@tool
def forensics_agent(user: str) -> str:
    """Review this user's spending and report only what needs a decision."""
    return forensics.review(user) or "nothing to report"


SUPERVISOR = """You are the case officer at the Tokens Bureau of Investigation.

You have a team. Use them in this order:

  scenario_agent   first, always. You cannot route what you have not read
  routing_agent    next, to pick the tier. Pass it the scenario report
  execution_agent  to actually do the work, once you have a tier
  forensics_agent  only when the person asks about their spending

Two standing rules.

Stop and ask the owner before running anything the scenario agent marked high
risk. Say what it is and what tier it needs. Do not decide that for them.

Report the answer to the work, not your process. Nobody wants to read which
tools you called. They want the email written or the question answered."""


def handle(request, user="demo", approve=None):
    """Run one request through the team.

    The approval gate is enforced here, in Python, before any agent starts.
    A supervisor told to ask first is a request, not a control: it can be talked
    out of it, and an approval a model grants itself is not an approval. This
    check runs on a keyword rule that costs nothing and cannot be argued with.
    """
    gate = router.heuristic(request)
    if approve and gate.tier in ("heavy", "max") and not approve(gate):
        return "declined by owner, nothing was run"

    supervisor = _agent(
        SUPERVISOR,
        tier="mid",
        tools=[scenario_agent, routing_agent, execution_agent, forensics_agent],
    )
    return str(supervisor(f"user: {user}\n\nrequest: {request}"))
