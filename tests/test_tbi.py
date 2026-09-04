"""Tests for the properties the pitch actually rests on.

Every one of these runs with no credentials, no Ollama and no network. A suite
that needs a live model is a suite nobody runs before a demo.
"""

import json

import pytest

from src import bureau, config, memory, pipeline, provider, router


class FakeCompletion:
    """Shaped like provider.Completion, with numbers we chose."""

    def __init__(self, text="ok", input_tokens=1000, output_tokens=500):
        self.text = text
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens


@pytest.fixture
def ledger(tmp_path, monkeypatch):
    """Never write to the developer's real ledger."""
    monkeypatch.setattr(memory, "LEDGER", str(tmp_path / "ledger.jsonl"))
    monkeypatch.setattr(memory, "FEEDBACK", str(tmp_path / "feedback.jsonl"))
    monkeypatch.setattr(memory, "TABLE", None)
    return tmp_path


class StubAgent:
    """Stands in for a Strands agent and drives the same hooks it would.

    Both lanes are real agents now, so faking provider.complete no longer
    intercepts anything: Strands talks to its own model object. Faking the
    agent instead keeps the gate and the ledger on the real code path.
    """

    def __init__(self, name, tier, case, used=(1000, 500)):
        self.name = name
        self.tier = tier
        self.case = case
        self.used = used
        self.event_loop_metrics = type("M", (), {"accumulated_usage": {
            "inputTokens": 0, "outputTokens": 0, "totalTokens": 0}})()
        self.model = type("Mod", (), {
            "get_config": lambda self: {"model_id": "stub"}})()

    def __call__(self, prompt):
        event = FakeEvent(self)
        if self.case:
            self.case.gate(event)
            if event.cancel:
                return "stopped: " + str(event.cancel)
        usage = self.event_loop_metrics.accumulated_usage
        usage["inputTokens"] += self.used[0]
        usage["outputTokens"] += self.used[1]
        if self.case:
            self.case.record(FakeEvent(self))
        return "ok"


@pytest.fixture
def offline(monkeypatch):
    """No network anywhere: the classifier and every agent are doubles.

    router imports complete by name, so patching provider alone would leave the
    classifier free to reach out on every request.
    """
    monkeypatch.setattr(provider, "complete", lambda *a, **k: FakeCompletion())

    def fake_classifier(model, prompt, max_tokens=None):
        """A stand in that agrees with the keyword rules, which is what a
        working classifier does on the obvious cases."""
        text = prompt.split("Request:", 1)[-1].strip()
        guess = router.heuristic(text)
        return FakeCompletion(json.dumps(
            {"tier": guess.tier, "domain": "email", "risk": guess.risk}))

    monkeypatch.setattr(router, "complete", fake_classifier)

    def fake_agent(system_prompt, tier="cheap", name="agent", tools=None):
        case = bureau._CASE.get()
        agent = StubAgent(name, tier, case)
        if case:
            case.assign(agent, tier)
        return agent

    monkeypatch.setattr(bureau, "agent", fake_agent)
    router._cache.clear()


# ------------------------------------------------------------------- counting


def test_price_is_the_arithmetic_it_claims():
    model = config.Model("test", input_cost=3.0, output_cost=15.0)
    # 1000 in at $3/M plus 500 out at $15/M = 0.003 + 0.0075
    assert memory.price(model, FakeCompletion()) == pytest.approx(0.0105)


def test_baseline_prices_the_tab_you_already_had_open():
    decision = router.Decision("cheap", "email", "low", "hi")
    record = memory.build("r1", "u", decision, "cheap", None, FakeCompletion())
    habit = memory.price(config.PRICED[config.HABIT_TIER], FakeCompletion())
    assert record.baseline_cost == pytest.approx(habit)
    assert record.baseline_cost > record.task_cost
    assert record.saved == pytest.approx(habit - record.total_cost)


def test_saving_is_never_negative_when_routing_goes_up():
    record = memory.Record("r", "u", "d", "max", "max", 0.0, 1.0, 1.0,
                           10, 10, 0.0, baseline_cost=0.5)
    assert record.saved == 0.0


# --------------------------------------------------------------------- safety


def test_the_keyword_fallback_never_reaches_the_top_tier():
    """A parse failure must not become an expensive call."""
    for text in ["irreversible decision", "x" * 3000, "", "max max max"]:
        assert router.heuristic(text).tier != "max"


def test_a_malformed_router_reply_falls_back_instead_of_failing():
    assert router._parse("not json at all", "text") is None
    assert router._parse('{"tier": "enormous"}', "text") is None
    assert router._parse('{"tier": "heavy"}', "text").tier == "heavy"


def test_the_ceiling_clamps_down_and_never_up():
    assert config.runnable("max") == config.CEILING
    assert config.runnable("cheap") == "cheap"


def test_an_unknown_ceiling_is_rejected_loudly():
    with pytest.raises(ValueError):
        config._tier("enormous", "mid")


def test_both_entry_points_ask_the_same_question():
    """The rule lives in one function, so the two paths cannot drift apart."""
    risky = router.Decision("max", "finance", "high", "t")
    safe = router.Decision("cheap", "email", "low", "t")
    assert bureau.needs_approval(risky)
    assert not bureau.needs_approval(safe)


def test_nothing_runs_when_approval_is_needed_and_absent(ledger, offline):
    result = pipeline.run("Should we terminate the Lisbon contract this quarter?",
                          user="u", approve=None)
    assert not result.approved
    assert result.record is None
    assert memory.records() == []


def test_a_refusal_stops_the_call(ledger, offline):
    result = pipeline.run("Should we terminate the Lisbon contract this quarter?",
                          user="u", approve=lambda d: False)
    assert not result.approved
    assert memory.records() == []


# ------------------------------------------------------------------ the hooks


class FakeAgent:
    def __init__(self, name="scenario"):
        self.name = name
        self.event_loop_metrics = type("M", (), {"accumulated_usage": {
            "inputTokens": 0, "outputTokens": 0, "totalTokens": 0}})()
        self.model = type("Mod", (), {"get_config": lambda self: {"model_id": "x"}})()


class FakeEvent:
    def __init__(self, agent):
        self.agent = agent
        self.cancel = False


def test_the_gate_cancels_a_call_above_the_authorised_tier():
    case = bureau.CaseFile(authorised="mid")
    agent = FakeAgent()
    case.assign(agent, "max")
    event = FakeEvent(agent)
    case.gate(event)
    assert event.cancel
    assert case.blocks[0].tier == "max"


def test_the_gate_lets_an_authorised_call_through():
    case = bureau.CaseFile(authorised="mid")
    agent = FakeAgent()
    case.assign(agent, "cheap")
    event = FakeEvent(agent)
    case.gate(event)
    assert event.cancel is False
    assert case.blocks == []


def test_the_gate_stops_a_runaway_loop_at_the_case_budget():
    case = bureau.CaseFile(authorised="max", budget=0.001)
    agent = FakeAgent()
    case.assign(agent, "cheap")
    case.calls.append(bureau.Call("x", "cheap", 1, 1, 0.002, 0.002))
    case.gate(event := FakeEvent(agent))
    assert "budget" in str(event.cancel)


def test_the_hook_records_the_delta_not_the_running_total():
    """Two calls on one agent must be two rows, not one row counted twice."""
    case = bureau.CaseFile()
    agent = FakeAgent()
    case.assign(agent, "heavy")

    agent.event_loop_metrics.accumulated_usage = {
        "inputTokens": 100, "outputTokens": 50, "totalTokens": 150}
    case.record(FakeEvent(agent))
    agent.event_loop_metrics.accumulated_usage = {
        "inputTokens": 300, "outputTokens": 90, "totalTokens": 390}
    case.record(FakeEvent(agent))

    assert [c.input_tokens for c in case.calls] == [100, 200]
    assert [c.output_tokens for c in case.calls] == [50, 40]
    assert case.spent == pytest.approx(
        memory.price(config.PRICED["heavy"], FakeCompletion(None, 300, 90)))


def test_a_call_that_used_nothing_is_not_recorded():
    case = bureau.CaseFile()
    case.record(FakeEvent(FakeAgent()))
    assert case.calls == []


def test_the_case_file_counts_the_team_not_just_the_answer():
    """Charging only for the final call would flatter us by the overhead."""
    case = bureau.CaseFile()
    for name in ("case officer", "scenario", "routing", "execution"):
        case.calls.append(bureau.Call(name, "cheap", 100, 50, 0.001, 0.01))
    record = memory.build_case("r", "u", router.Decision("cheap", "d", "low", ""), case)
    assert record.calls == 4
    assert record.task_cost == pytest.approx(0.004)
    assert record.input_tokens == 400


# ----------------------------------------------------------------- persistence


def test_a_ledger_row_written_before_a_field_existed_still_loads(ledger):
    old = {"request_id": "r", "user": "u", "domain": "email", "tier": "cheap",
           "ran_tier": "cheap", "router_cost": 0.0, "task_cost": 0.001,
           "decided_cost": 0.001, "input_tokens": 10, "output_tokens": 5,
           "at": 1.0}
    with open(memory.LEDGER, "w", encoding="utf-8") as handle:
        handle.write(json.dumps(old) + "\n")
    rows = memory.records()
    assert len(rows) == 1 and rows[0].baseline_cost == 0.0


def test_a_disliked_tier_moves_up_and_never_down():
    assert memory.escalate("cheap", {"rating": -1.0}) == "mid"
    assert memory.escalate("cheap", {"rating": 1.0}) == "cheap"
    assert memory.escalate("max", {"rating": -1.0}) == "max"
    assert memory.escalate("cheap", None) == "cheap"


def test_tokens_in_the_ledger_come_from_the_provider(ledger, offline):
    """The one property everything else rests on."""
    result = pipeline.run("write a short email to a supplier", user="u")
    assert result.record.input_tokens == 1000
    assert result.record.output_tokens == 500
    assert result.path == "solo"
    assert memory.records()[0].request_id == result.record.request_id


def test_the_system_sends_judgement_work_to_the_team(ledger, offline):
    """The lane is chosen for you, and the ledger says which one ran."""
    result = pipeline.run("Negotiate the packaging supplier's new terms",
                          user="u", approve=lambda d: True)
    assert result.path == "team"
    assert result.record.calls >= 1


def test_every_lane_is_watched(ledger, offline):
    """A solo agent is still an agent, so the hooks still record it."""
    seen = []
    pipeline.run("write a short email", user="u", watch=seen.append)
    assert [e["kind"] for e in seen] == ["call"]
    assert seen[0]["agent"] == "assistant"


def test_the_classifier_pays_for_itself_and_the_ledger_says_so(ledger, offline):
    """Choosing the tier costs a model call, and that call is a cost like any
    other. Recording it as zero would make routing look free."""
    result = pipeline.run("Summarise these meeting notes please", user="u")
    assert result.record.router_cost > 0
    assert result.record.total_cost > result.record.task_cost


def test_an_identical_request_is_decided_from_cache_for_nothing(offline):
    long_request = "Summarise these meeting notes. " + "detail " * 200
    first, spend = router.decide(long_request)
    second, no_spend = router.decide(long_request)
    assert spend is not None and no_spend is None
    assert second.cached and second.tier == first.tier


def test_an_override_skips_classification_but_not_the_ledger(ledger, offline):
    """A tier the person chose is still a tier somebody paid for."""
    result = pipeline.run("anything at all", user="u", tier="cheap")
    assert result.decision.domain == "override"
    assert result.record.router_cost == 0.0
    assert result.record.ran_tier == "cheap"
    assert len(memory.records()) == 1


# ------------------------------------------------------------- the interface


@pytest.fixture
def server(ledger):
    """Load ui/server.py the way running it loads it."""
    import importlib.util
    import pathlib

    path = pathlib.Path(__file__).resolve().parent.parent / "ui" / "server.py"
    spec = importlib.util.spec_from_file_location("tbi_server", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.TITLES = ledger / ".titles.json"
    return module


def test_the_saving_compares_one_window_against_itself(server, ledger):
    """Dividing this month's spend by all of history's baseline reports a
    number that means nothing. Both sides must cover the same requests."""
    import time as clock

    now = clock.time()
    old = memory.Record("old", "demo", "email", "cheap", "cheap", 0.0, 1.0, 1.0,
                        10, 5, now - 90 * 86400, baseline_cost=9.0)
    recent = memory.Record("new", "demo", "email", "cheap", "cheap", 0.0, 1.0, 1.0,
                           10, 5, now - 60, baseline_cost=4.0)
    memory.save(old)
    memory.save(recent)

    result = server.state()
    # Only the recent row is inside the month: 1.00 spent against 4.00 baseline.
    assert result["month"] == pytest.approx(1.0)
    assert result["baseline"] == pytest.approx(4.0)
    assert result["saved"] == pytest.approx(75.0)


def test_an_empty_ledger_reports_no_saving_rather_than_zero(server):
    """Nothing measured is not the same as nothing saved."""
    result = server.state()
    assert result["history"] == []
    assert result["saved"] is None


def test_the_interface_asks_before_it_spends(server, offline):
    """The gate returns the question, and runs nothing."""
    answer = server.ask("Should we terminate the Lisbon contract this quarter?",
                        approved=False)
    assert "needs_approval" in answer
    assert memory.records() == []


def test_the_interface_reports_when_no_backend_is_reachable(server):
    """A short label for the sidebar, the full sentence and the fix behind it."""
    ready, message = server.provider.health()
    result = server.state()
    assert result["backend_detail"] == message
    assert result["backend"].endswith("ready" if ready else "offline")


# ------------------------------------------------------- routing you control


def test_the_system_picks_the_path_not_the_person():
    """Six model calls versus one is a latency decision, so we make it."""
    assert router.needs_team(router.Decision("heavy", "legal", "low", ""))
    assert router.needs_team(router.Decision("cheap", "email", "high", ""))
    assert not router.needs_team(router.Decision("cheap", "email", "low", ""))
    assert not router.needs_team(router.Decision("mid", "coding", "low", ""))


def test_a_pinned_domain_beats_the_classifier(monkeypatch):
    decision = router.Decision("cheap", "coding", "low", "x")
    monkeypatch.setattr(config, "DOMAIN_RULES", {"coding": "heavy"})
    assert router.apply_rules(decision).tier == "heavy"


def test_a_pinned_rule_naming_a_bad_tier_is_ignored(monkeypatch):
    decision = router.Decision("cheap", "coding", "low", "x")
    monkeypatch.setattr(config, "DOMAIN_RULES", {"coding": "enormous"})
    assert router.apply_rules(decision).tier == "cheap"


def test_settings_reject_a_bad_value_at_the_boundary():
    from src import settings

    good = settings.defaults()
    settings.validate(good)
    for bad in ({"ceiling": "enormous"}, {"habit": ""}, {"case_budget": 0}):
        with pytest.raises(ValueError):
            settings.validate({**good, **bad})


def test_settings_reject_a_negative_price():
    from src import settings

    values = settings.defaults()
    values["tiers"]["mid"]["input_cost"] = -1
    with pytest.raises(ValueError):
        settings.validate(values)


def test_usage_totals_agree_with_the_ledger_they_came_from(ledger):
    import time as clock

    now = clock.time()
    for i in range(3):
        memory.save(memory.Record(f"u{i}", "demo", "email", "cheap", "cheap",
                                  0.0, 0.002, 0.002, 100, 50, now - i * 60,
                                  baseline_cost=0.010, calls=2))
    report = memory.usage("demo")
    assert report["totals"]["cases"] == 3
    assert report["totals"]["calls"] == 6
    assert report["totals"]["tokens"] == 450
    assert report["totals"]["cost"] == pytest.approx(0.006)
    assert report["totals"]["saved"] == pytest.approx(0.024)
    assert report["totals"]["saved_pct"] == pytest.approx(80.0)


def test_usage_on_an_empty_ledger_reports_nothing_not_zero(ledger):
    assert memory.usage("demo")["totals"]["saved_pct"] is None


def test_a_looping_agent_is_stopped_by_call_count_not_only_by_cost():
    """Locally the model is free, so a dollar budget never fires. A small model
    calling tools in circles is exactly the local failure mode."""
    case = bureau.CaseFile(authorised="max", max_calls=3)
    agent = FakeAgent()
    case.assign(agent, "cheap")
    for _ in range(3):
        case.calls.append(bureau.Call("x", "cheap", 1, 1, 0.0, 0.0))
    case.gate(event := FakeEvent(agent))
    assert "loop" in str(event.cancel)
    assert case.spent == 0.0
