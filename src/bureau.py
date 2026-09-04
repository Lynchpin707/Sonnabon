"""The evidence room.

One Strands hook provider, registered on the team, doing the two things TBI
exists to do:

    BeforeModelCall   stop a call nobody authorised
    AfterModelCall    record what the call actually cost

Both run inside the SDK's own agent loop, which is the point. A supervisor told
in its system prompt to ask permission first is making a request, and a model
can talk itself out of a request. A hook that sets ``event.cancel`` is a
control, and the model is not consulted.

Because Strands fires these for every agent in the team, the team's own
overhead lands in the ledger too. A cost tracker that does not count its own
agents is committing the exact error it was built to catch.
"""

import os
from contextvars import ContextVar
from dataclasses import dataclass, field

from strands import Agent
from strands.hooks import (AfterModelCallEvent, AfterToolCallEvent,
                           BeforeModelCallEvent, BeforeToolCallEvent,
                           HookProvider)

from . import config, memory

# A whole case, agents included, that costs more than this has gone wrong.
# Cheap to check, and it is the only thing standing between a demo and a
# runaway loop billed to a student account.
CASE_BUDGET = float(os.getenv("CASE_BUDGET_USD", "0.25"))

# A full team pass is about six model calls. Past this, the coordinator is
# looping rather than working. Strands caps iterations on Swarm but not on a
# plain Agent, and small local models are exactly the ones that loop, so the
# ceiling lives here where the gate already runs.
CASE_MAX_CALLS = int(os.getenv("CASE_MAX_CALLS", "14"))


@dataclass(frozen=True)
class Call:
    """One model call, as the provider reported it."""

    agent: str
    tier: str
    input_tokens: int
    output_tokens: int
    cost: float
    baseline_cost: float


@dataclass(frozen=True)
class Block:
    """One call the gate refused, and why."""

    agent: str
    tier: str
    reason: str


def _tier_of(model_id):
    """Fallback for an agent built outside bureau.agent. Local development maps
    three tiers onto one model, so this cannot always be exact; the case file
    records the tier it was asked for instead. Unknown models are treated as the
    most expensive tier, because an unrecognised model is when to be careful."""
    for tier, model in config.MODELS.items():
        if model.id == model_id:
            return tier
    return config.TIER_ORDER[-1]


@dataclass
class CaseFile(HookProvider):
    """Registered once, on every agent. Holds one request's evidence."""

    user: str = "demo"
    authorised: str = config.CEILING
    budget: float = CASE_BUDGET
    # Called with each step as it happens, so an interface can show the work
    # being done instead of only the receipt afterwards. Fired from the agent
    # loop's own threads, so whatever is on the other end must be thread safe.
    watch: object = None
    max_calls: int = CASE_MAX_CALLS
    calls: list = field(default_factory=list)
    blocks: list = field(default_factory=list)
    _seen: dict = field(default_factory=dict)
    _tiers: dict = field(default_factory=dict)

    def assign(self, agent, tier):
        """Remember which tier an agent was built for. Reading it back off the
        model id would be wrong locally, where three tiers share one model."""
        self._tiers[id(agent)] = tier

    def tier_of(self, agent):
        return self._tiers.get(
            id(agent), _tier_of(agent.model.get_config().get("model_id")))

    # ------------------------------------------------------------ the hooks

    def register_hooks(self, registry, **kwargs):
        registry.add_callback(BeforeModelCallEvent, self.gate)
        registry.add_callback(AfterModelCallEvent, self.record)
        registry.add_callback(BeforeToolCallEvent, self.consulting)
        registry.add_callback(AfterToolCallEvent, self.consulted)

    def say(self, **event):
        if self.watch:
            try:
                self.watch(event)
            except Exception:
                # A viewer that has gone away must not take the case with it.
                self.watch = None

    def consulting(self, event):
        """The case officer is handing work to a specialist."""
        self.say(kind="tool", state="start",
                 agent=str(event.tool_use.get("name", "specialist")))

    def consulted(self, event):
        self.say(kind="tool", state="done",
                 agent=str(event.tool_use.get("name", "specialist")),
                 seconds=round(event.duration or 0, 2))

    def gate(self, event):
        """Refuse the call, before it is billed, if it is not allowed."""
        agent = getattr(event.agent, "name", "agent")
        tier = self.tier_of(event.agent)

        if len(self.calls) >= self.max_calls:
            return self._block(event, agent, tier,
                               f"stopped after {len(self.calls)} model calls. "
                               f"A full pass takes about six, so this is a loop")

        if self.spent >= self.budget:
            return self._block(event, agent, tier,
                               f"case budget of ${self.budget:.2f} already spent "
                               f"over {len(self.calls)} calls")

        if config.TIER_ORDER.index(tier) > config.TIER_ORDER.index(self.authorised):
            return self._block(event, agent, tier,
                               f"{tier} tier is above the authorised {self.authorised}")

    def record(self, event):
        """Read what the provider charged. Never an estimate, never a guess."""
        usage = event.agent.event_loop_metrics.accumulated_usage
        key = id(event.agent)
        before_in, before_out = self._seen.get(key, (0, 0))
        self._seen[key] = (usage["inputTokens"], usage["outputTokens"])

        used = _Usage(usage["inputTokens"] - before_in,
                      usage["outputTokens"] - before_out)
        if used.input_tokens <= 0 and used.output_tokens <= 0:
            return

        tier = self.tier_of(event.agent)
        call = Call(
            agent=getattr(event.agent, "name", "agent"),
            tier=tier,
            input_tokens=used.input_tokens,
            output_tokens=used.output_tokens,
            cost=memory.price(config.PRICED[tier], used),
            baseline_cost=memory.price(config.PRICED[config.HABIT_TIER], used),
        )
        self.calls.append(call)
        self.say(kind="call", agent=call.agent, tier=call.tier, cost=call.cost,
                 input_tokens=call.input_tokens, output_tokens=call.output_tokens)

    # ------------------------------------------------------------- the totals

    @property
    def spent(self):
        return sum(call.cost for call in self.calls)

    @property
    def baseline(self):
        """What these same tokens cost on the tab they already had open."""
        return sum(call.baseline_cost for call in self.calls)

    def _block(self, event, agent, tier, reason):
        event.cancel = reason
        self.blocks.append(Block(agent, tier, reason))
        self.say(kind="block", agent=agent, tier=tier, reason=reason)


@dataclass(frozen=True)
class _Usage:
    """Shaped like a Completion so memory.price takes it unchanged."""

    input_tokens: int
    output_tokens: int


# ------------------------------------------------------------------ the rule


def needs_approval(decision):
    """The one rule both entry points use.

    A request may proceed on standing authority when it stays at or below the
    ceiling and the scenario is not high risk. Anything else is the owner's
    call. Keeping the rule in one function is what stops the fast path and the
    agent team from quietly disagreeing about what "high risk" means.
    """
    above = (config.TIER_ORDER.index(decision.tier)
             > config.TIER_ORDER.index(config.CEILING))
    return above or decision.risk == "high"


# --------------------------------------------------------------- the team kit

_CASE = ContextVar("case", default=None)


def open_case(case):
    """Bind a case file for the duration of one request. Every agent built
    while it is bound is wired to it, so no agent can be created without its
    calls being recorded."""
    return _CASE.set(case)


def close_case(token):
    _CASE.reset(token)


def model(tier):
    if config.USE_AWS:
        from strands.models.bedrock import BedrockModel

        return BedrockModel(model_id=config.MODELS[tier].id,
                            region_name=config.AWS_REGION)

    from strands.models.ollama import OllamaModel

    return OllamaModel(host=config.OLLAMA_HOST, model_id=config.MODELS[tier].id)


def agent(system_prompt, tier="cheap", name="agent", tools=None):
    """Every agent in the bureau is built here, so every agent is watched."""
    case = _CASE.get()
    built = Agent(
        model=model(tier),
        system_prompt=system_prompt,
        tools=tools or [],
        name=name,
        hooks=[case] if case else [],
    )
    if case:
        case.assign(built, tier)
    return built
