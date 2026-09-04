"""The agents.

Two lanes, both Strands. ``solo`` is one agent with no tools and handles most
traffic at a single call. ``team`` is a coordinator with four specialists
exposed to it as tools, which is how a team is assembled in Strands.

Every agent is built by ``bureau.agent``, so every agent is wired to the same
case file and no model call happens off the books.

The allocator is told what this system can actually reach, generated from
config, so adding a model changes what it knows without editing a prompt.
"""

from strands import tool

from . import bureau, config, forensics, memory, router

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

ALLOCATOR = """You choose which model answers a request.

These are the models this system can actually reach right now, with what they
cost per million tokens:

{catalogue}

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


def catalogue():
    """What this system can actually call, priced, as the allocator sees it.

    Generated from config rather than written into the prompt, so adding a
    model or renegotiating a rate changes what the allocator knows without
    anybody editing a system prompt and forgetting the other copy.
    """
    return "\n".join(
        f"  {tier:<6} {model.id:<34} "
        f"${model.input_cost:g} in / ${model.output_cost:g} out"
        for tier, model in config.PRICED.items())


def allocator_prompt():
    return ALLOCATOR.format(catalogue=catalogue())


EXECUTION = """You do the work the request asks for.

Answer the request itself. Do not describe what you are about to do, do not
restate the question, and do not offer further help at the end."""

SUPERVISOR = """You coordinate a small team that answers one request.

You have four specialists. Use them in this order:

  scenario_agent   first, always. You cannot allocate what you have not read
  allocator_agent  next, to pick the model. Pass it the scenario report
  execution_agent  to do the work, once you have a model
  auditor_agent    only when the person asks about their spending

Report the answer to the work, not your process. Nobody wants to read which
tools you called. They want the email written or the question answered."""


@tool
def scenario_agent(request: str) -> str:
    """Read a request and report its intent, complexity, risk and domain."""
    return str(bureau.agent(SCENARIO, "cheap", "scenario")(request))


@tool
def allocator_agent(scenario_report: str, user: str) -> str:
    """Choose the model for a request, from what this system can reach, using
    this user's rating history."""
    decision = router.heuristic(scenario_report)
    past = memory.prior(user, decision.domain)
    history = (
        f"prior in this domain: {past['n']} requests, usual tier {past['tier']}, "
        f"mean rating {past['rating']}"
        if past
        else "no history for this user in this domain"
    )
    return str(bureau.agent(allocator_prompt(), "cheap", "allocator")(
        f"{scenario_report}\n\n{history}"))


@tool
def execution_agent(tier: str, request: str) -> str:
    """Run the request on the chosen tier. The cost is recorded by the hooks."""
    if tier not in config.TIER_ORDER:
        tier = "mid"
    ran = config.runnable(tier)
    return str(bureau.agent(EXECUTION, ran, "execution")(
        router.adapt(request, tier)))


@tool
def auditor_agent(user: str) -> str:
    """Review this user's spending and report only what needs a decision."""
    return forensics.review(user) or "nothing to report"


def solo(text, decision):
    """One agent, no tools, for work with a known shape.

    Still a Strands agent, so the hooks record it and the gate can stop it.
    The saving is in the number of calls, not in skipping the controls.
    """
    ran = config.runnable(decision.tier)
    agent = bureau.agent(EXECUTION, ran, "assistant")
    return str(agent(router.adapt(text, decision.tier)))


def team(text, user="demo"):
    """A coordinator and four specialists, for work that needs judgement."""
    coordinator = bureau.agent(
        SUPERVISOR, "mid", "coordinator",
        tools=[scenario_agent, allocator_agent, execution_agent, auditor_agent],
    )
    return str(coordinator(f"user: {user}\n\nrequest: {text}"))
