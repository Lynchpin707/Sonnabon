"""The agent team.

Two lanes, both Strands. ``solo`` is one agent with no tools and handles most
traffic. ``team`` is a case officer with four specialists exposed to it as
tools, which is how a team is assembled in Strands.

Every agent here is built by ``bureau.agent``, so every agent is wired to the
same case file. Nobody in this building can make a model call off the books.

Names say the job. Nothing here is called a prosecutor.
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

EXECUTION = """You do the work the request asks for.

Answer the request itself. Do not describe what you are about to do, do not
restate the question, and do not offer further help at the end."""

SUPERVISOR = """You are the case officer at the Tokens Bureau of Investigation.

You have a team. Use them in this order:

  scenario_agent   first, always. You cannot route what you have not read
  routing_agent    next, to pick the tier. Pass it the scenario report
  execution_agent  to do the work, once you have a tier
  forensics_agent  only when the person asks about their spending

Report the answer to the work, not your process. Nobody wants to read which
tools you called. They want the email written or the question answered."""


@tool
def scenario_agent(request: str) -> str:
    """Read a request and report its intent, complexity, risk and domain."""
    return str(bureau.agent(SCENARIO, "cheap", "scenario")(request))


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
    return str(bureau.agent(ROUTING, "cheap", "routing")(
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
def forensics_agent(user: str) -> str:
    """Review this user's spending and report only what needs a decision."""
    return forensics.review(user) or "nothing to report"


def solo(text, decision):
    """One agent, no tools, for work with a known shape.

    Still a Strands agent, so the hooks record it and the gate can stop it.
    The saving is in the number of calls, not in skipping the controls.
    """
    ran = config.runnable(decision.tier)
    officer = bureau.agent(EXECUTION, ran, "duty officer")
    return str(officer(router.adapt(text, decision.tier)))


def team(text, user="demo"):
    """A case officer and four specialists, for work that needs judgement."""
    officer = bureau.agent(
        SUPERVISOR, "mid", "case officer",
        tools=[scenario_agent, routing_agent, execution_agent, forensics_agent],
    )
    return str(officer(f"user: {user}\n\nrequest: {text}"))
