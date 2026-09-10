"""One agent, and the limits it cannot argue with.

The agent decides and acts. What stops it doing something expensive or
irreversible is not a paragraph in its system prompt, because a paragraph is a
request and a model can talk itself out of a request. It is a hook that fires
inside the SDK's own loop and sets ``event.cancel``, which the model is never
consulted about.

Three limits, all of them cheap to check and all of them the sort of thing that
only matters once:

    calls    a run that has made thirty tool calls is looping, not working
    spend    a run that has cost more than a few cents has gone wrong
    actions  sending an order or an email is not something to do twice
"""

import os
import time
from dataclasses import dataclass, field

from strands import Agent
from strands.hooks import (AfterModelCallEvent, BeforeModelCallEvent,
                           BeforeToolCallEvent, HookProvider)

from . import model as models, tools

MAX_TOOL_CALLS = int(os.getenv("MAX_TOOL_CALLS", "30"))
MAX_RUN_COST = float(os.getenv("MAX_RUN_COST_USD", "0.15"))

# Tools that change something outside the agent. Everything else is reading.
# These names have to match the tool names exactly or the gate silently never
# fires, which is the worst possible failure for a control: it looks present.
ACTIONS = {"notify_owner"}

SYSTEM = """You are Sonnabon, the operations and planning manager for a small
bakery. You were hired once and you now run the production side without being
asked.

Your job each run:
  read what the data says, decide, act, and stay quiet unless something genuinely
  needs the owner.

How you work:
  Call right_now first, then shop_status, so you know what time it is and what
  period the figures cover. A shortfall at nine in the morning and the same one
  at closing are not the same fact.
  If the shop is still open and somebody asks how today is going, sales_so_far
  is the only tool that can see it. Everything else reads finished days.
  Use the tools for anything they cover. Use run_python for anything else.
  The summaries answer almost everything. When they do not, sample_bills shows
  you real receipts, and run_python works over all of them at once. Never ask
  for a whole day of raw bills: it will not fit and it is not needed.
  Never do arithmetic in your head. Write code and run it. Every number you give
  the owner must have come from a tool or from code you executed.
  Sales are not demand. On days a product ran out, the till undercounts. The
  tools correct for this and tell you their confidence. Quote the confidence.
  You hand out the work, so read team_board to see what came back. A sell-out
  somebody confirmed is a fact; one nobody confirmed is still your inference,
  and the difference belongs in what you say. If confirmations stop coming
  back, the numbers get weaker every night, and that is worth raising once.

How you talk to the owner:
  Like a colleague who has been here a while, not a report. Short sentences.
  Say what you did, not what you could do.
  Give one recommendation, not a menu of options.
  If you are asking something, say what you will do by default if they do not
  answer, and by when.

What you never do:
  Change suppliers, agree prices, or commit to anything contractual.
  Claim a number you did not compute.
  Ask about something you could have worked out yourself."""


@dataclass
class Ledger(HookProvider):
    """Counts what a run did, and stops it when it stops making sense."""

    max_calls: int = MAX_TOOL_CALLS
    max_cost: float = MAX_RUN_COST
    input_rate: float = 1.00 / 1_000_000       # per token, cheap tier default
    output_rate: float = 5.00 / 1_000_000
    watch: object = None
    began: float = field(default_factory=time.monotonic)
    calls: int = 0
    tool_calls: list = field(default_factory=list)
    blocked: list = field(default_factory=list)
    refused: list = field(default_factory=list)   # actions stopped at the gate
    input_tokens: int = 0
    output_tokens: int = 0
    approvals: dict = field(default_factory=dict)

    # ---------------------------------------------------------------- hooks

    def register_hooks(self, registry, **kwargs):
        registry.add_callback(BeforeModelCallEvent, self.before_model)
        registry.add_callback(AfterModelCallEvent, self.after_model)
        registry.add_callback(BeforeToolCallEvent, self.before_tool)

    def before_model(self, event):
        if self.cost > self.max_cost:
            self._stop(event, f"run has cost ${self.cost:.4f}, over the "
                              f"${self.max_cost:.2f} ceiling")
        elif self.calls >= self.max_calls:
            self._stop(event, f"{self.calls} tool calls without finishing, "
                              "which is looping rather than working")

    def after_model(self, event):
        usage = self._usage(event)
        if usage:
            self.input_tokens += usage[0]
            self.output_tokens += usage[1]
        self.say(kind="thinking", cost=round(self.cost, 5))

    def before_tool(self, event):
        name = getattr(event, "tool_use", None)
        name = (name or {}).get("name") if isinstance(name, dict) else \
            getattr(name, "name", None)
        self.calls += 1
        self.tool_calls.append(name)
        self.say(kind="tool", tool=name, n=self.calls)

        if name in ACTIONS:
            # An irreversible action runs once. The gate used to require an
            # entry in ``approvals`` that nothing ever supplied, so the one
            # thing this agent exists to do was blocked every time, and nothing
            # noticed because no model had run. Once is the rule the docstring
            # always described: the second send is the dangerous one, not the
            # first. Refusing here rather than in the prompt is still the
            # difference between a control and a suggestion.
            allowed = int(self.approvals.get(name, 1))
            if self.tool_calls.count(name) - self.refused.count(name) > allowed:
                self.refused.append(name)
                self._stop(event,
                           f"{name} has already run {allowed} time(s) this "
                           f"run, and sending the same decision twice is worse "
                           f"than not sending it")

    # -------------------------------------------------------------- helpers

    @staticmethod
    def _usage(event):
        """Read token counts from whatever shape the provider reports.

        Providers disagree on this and the SDK surfaces it differently across
        versions, so failing to find it must cost the ledger accuracy, never the
        run. An uncounted call is better than a crashed one.
        """
        for path in ("usage", "response.usage", "result.usage"):
            target = event
            for part in path.split("."):
                target = getattr(target, part, None)
                if target is None:
                    break
            if target is None:
                continue
            read = (lambda key: getattr(target, key, None)
                    if not isinstance(target, dict) else target.get(key))
            given = read("inputTokens") or read("input_tokens") or 0
            made = read("outputTokens") or read("output_tokens") or 0
            if given or made:
                return int(given), int(made)
        return None

    def _stop(self, event, reason):
        self.blocked.append(reason)
        self.say(kind="blocked", reason=reason)
        event.cancel = f"Stopped: {reason}."

    def say(self, **event):
        if not self.watch:
            return
        try:
            self.watch(event)
        except Exception:
            # A viewer that has gone away must not take the run with it.
            self.watch = None

    @property
    def cost(self):
        return (self.input_tokens * self.input_rate
                + self.output_tokens * self.output_rate)

    @property
    def seconds(self):
        return round(time.monotonic() - self.began, 2)

    def report(self):
        return {"tool_calls": self.calls, "tools": self.tool_calls,
                "input_tokens": self.input_tokens,
                "output_tokens": self.output_tokens,
                "cost_usd": round(self.cost, 5), "seconds": self.seconds,
                # Counted from the tools that actually ran, not from what the
                # closing paragraph claims and not from attempts the gate
                # stopped. An agent that says it emailed you and did not is the
                # one failure nobody would catch.
                "notified": sum(1 for name in self.tool_calls
                                if name in ACTIONS) - len(self.refused),
                "blocked": self.blocked}


TOOLS = [tools.right_now, tools.sales_so_far, tools.shop_status, tools.day_report, tools.sample_bills,
         tools.bake_plan,
         tools.best_sellers, tools.trade_summary, tools.lost_to_sellouts,
         tools.product_trends, tools.whats_coming, tools.occasion_plan, tools.team_board,
         tools.find_local_events, tools.notify_owner, tools.run_python]


def build(model=None, watch=None, approvals=None, extra_tools=()):
    """The agent, with its limits attached.

    ``model`` is left to the caller so nothing here depends on which provider is
    available. Left None it resolves one from what is configured, which is
    Bedrock in deployment and Ollama on a laptop, and raises something readable
    when neither is.
    """
    ledger = Ledger(watch=watch, approvals=dict(approvals or {}))
    agent = Agent(
        model=model if model is not None else models.resolve(),
        system_prompt=SYSTEM,
        tools=list(TOOLS) + list(extra_tools),
        hooks=[ledger],
    )
    return agent, ledger
