"""What has to stay true.

Two kinds of test here. Most are ordinary: a function does what it says. A few
are the interesting ones, and they score the agent's estimates against demand
that is genuinely known, which is only possible because the shop is generated.

They run on a small deterministic slice, not the year in ``data/``, so they are
fast and so a clone with no data still passes.
"""

import math
from datetime import date, timedelta

import pytest

from src.bakery.core import analytics, calendar, catalogue, plan, receipts

from src.bakery.simulation import generate

NEWLINE = chr(10)


@pytest.fixture(scope="module")
def shop():
    """Four months of trade, seeded, with the truth kept alongside."""
    bills, truth = generate.simulate(date(2025, 1, 6), date(2025, 5, 4), seed=11)
    index = analytics.Index(bills)
    return {"bills": bills, "index": index,
            "truth": {row["day"]: row["products"] for row in truth}}


# ── the menu ────────────────────────────────────────────────────────────────

def test_service_level_is_higher_for_cheap_perishables():
    """The counterintuitive result the whole plan rests on.

    Running out of something cheap costs the margin; binning it costs almost
    nothing. Expensive pastry is the other way round. If this ever inverts, the
    plan is quietly making the wrong thing.
    """
    cookie = catalogue.get("Chocolate chip cookie")
    cake = catalogue.get("Tiramisu")
    assert cookie.critical_ratio > cake.critical_ratio
    assert cookie.price < cake.price


def test_salvage_above_cost_is_refused():
    """An unsold unit worth more than it cost would make over-baking free."""
    with pytest.raises(ValueError, match="not below cost"):
        catalogue.Product("Impossible", "x", 4.0, 1.0, 2.0, 1, salvage=1.5)


def test_price_below_cost_is_refused():
    with pytest.raises(ValueError, match="does not cover cost"):
        catalogue.Product("Loss maker", "x", 1.0, 2.0, 2.0, 1)


def test_menu_is_learned_from_the_bills(shop):
    """Nothing about the shop should have to be typed in."""
    learned = catalogue.learn(shop["bills"], food_cost=0.3, no_waste=["Coffee"])
    names = {product.name for product in learned}
    assert "Croissant" in names and "Coffee" in names
    coffee = next(p for p in learned if p.name == "Coffee")
    assert coffee.bake_minutes == 0, "coffee is not a production decision"
    assert all(p.cost > 0 for p in learned)
    assert all(not p.cost_given for p in learned), "nothing was told to it yet"


def test_guessed_costs_are_what_it_asks_about():
    learned = catalogue.learn([], food_cost=0.3)
    assert learned == []


# ── sell-outs, scored against the truth ─────────────────────────────────────

def test_detector_finds_real_sellouts_without_crying_wolf(shop):
    """Precision matters more than recall here.

    A missed sell-out costs one day's correction. A false one inflates the
    headline loss, and an inflated headline is how an audience stops believing
    the rest of it.
    """
    found = {(row["day"].isoformat(), row["item"])
             for row in analytics.find_sellouts(shop["bills"], index=shop["index"])}
    real = {(day, item) for day, products in shop["truth"].items()
            for item, record in products.items() if record["sold_out_at"]}
    hits = found & real
    precision = len(hits) / len(found)
    recall = len(hits) / len(real)
    assert precision >= 0.75, f"precision fell to {precision:.0%}"
    assert recall >= 0.55, f"recall fell to {recall:.0%}"


def test_demand_estimate_is_close_to_the_truth(shop):
    """The claim the product is built on, checked against known demand."""
    priced = analytics.lost_to_sellouts(shop["bills"], index=shop["index"])
    errors = []
    for row in priced["rows"]:
        if row["confidence"] not in ("good", "fair"):
            continue
        record = shop["truth"].get(row["day"].isoformat(), {}).get(row["item"])
        if not record or not record["sold_out_at"]:
            continue
        errors.append(abs(row["estimate"] - record["wanted"]) / record["wanted"])

    assert len(errors) > 30, "too few scored days to mean anything"
    errors.sort()
    median = errors[len(errors) // 2]
    within = sum(1 for value in errors if value <= 0.25) / len(errors)
    assert median <= 0.12, f"median error rose to {median:.1%}"
    assert within >= 0.80, f"only {within:.0%} of days within 25%"


def test_estimate_never_undercuts_what_actually_sold(shop):
    """Demand cannot be lower than the number of units that left the shelf."""
    priced = analytics.lost_to_sellouts(shop["bills"], index=shop["index"])
    for row in priced["rows"]:
        assert row["estimate"] >= row["sold"]


def test_low_confidence_is_reported_separately(shop):
    """A poor estimate must not be folded into the headline figure."""
    priced = analytics.lost_to_sellouts(shop["bills"], index=shop["index"])
    assert priced["lost_margin"] <= priced["lost_margin_including_poor"]


# ── the plan ────────────────────────────────────────────────────────────────

def test_plan_uses_corrected_history_not_raw_sales(shop):
    """The correction has to reach the forecast, or none of it matters."""
    history, corrected = plan.corrected_history(shop["bills"], index=shop["index"])
    assert corrected, "nothing was corrected at all"
    item, days = next(iter(corrected.items()))
    day = next(iter(days))
    assert history[item][day] > shop["index"].units[day][item]


def test_plan_makes_more_of_the_thing_that_ran_out(shop):
    """The point of the correction, stated as a test."""
    history, corrected = plan.corrected_history(shop["bills"], index=shop["index"])
    target = max(shop["index"].units) + timedelta(days=1)
    built = plan.bake_plan(shop["bills"], target, index=shop["index"],
                           history=history)
    for row in built["rows"]:
        assert row["make"] >= 0
        if row["forecast"] > 0:
            assert row["make"] >= row["forecast"] * 0.5, row["item"]


def test_capacity_never_trims_below_forecast(shop):
    """Trimming into expected demand manufactures the sell-out we exist to stop."""
    history, _ = plan.corrected_history(shop["bills"], index=shop["index"])
    target = max(shop["index"].units) + timedelta(days=1)
    free = plan.bake_plan(shop["bills"], target, index=shop["index"],
                          history=history)
    tight = plan.bake_plan(shop["bills"], target, index=shop["index"],
                           history=history,
                           oven_minutes=free["oven_minutes"] * 0.6)
    for row in tight["rows"]:
        tray = plan.tray_for(catalogue.get(row["item"]), row["forecast"])
        assert row["make"] >= math.ceil(row["forecast"] / tray) * tray, row["item"]


def test_quantity_respects_the_service_level():
    """A higher critical ratio has to mean more units, all else equal."""
    cookie = catalogue.get("Chocolate chip cookie")
    cake = catalogue.get("Tiramisu")
    assert (plan.quantity(cookie, 50, 10) / 50) > (plan.quantity(cake, 50, 10) / 50)


# ── trends ──────────────────────────────────────────────────────────────────

def test_trend_refuses_to_call_noise_a_trend(shop):
    """Owners kill products after two bad weeks. The refusal is the feature."""
    history, _ = plan.corrected_history(shop["bills"], index=shop["index"])
    result = analytics.trends(shop["bills"], weeks=12, index=shop["index"],
                              history=history)
    moving = len(result["growing"]) + len(result["declining"])
    assert result["flat"] >= moving, "calling almost everything a trend"


# ── the calendar ────────────────────────────────────────────────────────────

def test_occasions_are_found_before_they_arrive():
    """Christmas in December is a warning. In October it is a decision."""
    rows = calendar.upcoming(date(2025, 10, 20), within_days=80)
    assert any(row["occasion"] == "Christmas" for row in rows)


def test_schedule_flags_what_is_already_late():
    """A plan that only lists what is coming hides a missed order."""
    result = calendar.schedule("Christmas", date(2025, 12, 20))
    assert result["tasks"], "no run-up at all"
    assert any(task["overdue"] for task in result["tasks"])


def test_occasion_lift_peaks_on_the_day_and_fades_before_it():
    on_day = calendar.multiplier(date(2025, 12, 25), "Basque cheesecake")
    early = calendar.multiplier(date(2025, 12, 14), "Basque cheesecake")
    away = calendar.multiplier(date(2025, 8, 3), "Basque cheesecake")
    assert on_day > early >= away == 1.0


# ── receipts ────────────────────────────────────────────────────────────────

def test_unknown_products_are_refused_at_the_door(tmp_path):
    """A typo must not become a silent zero cost three modules later."""
    path = tmp_path / "bills.jsonl"
    path.write_text('{"number":1,"at":"2025-01-06T08:00:00",'
                    '"lines":[{"item":"Ghost bun","qty":1,"unit_price":2.0}]}',
                    encoding="utf-8")
    with pytest.raises(KeyError, match="not on the menu"):
        receipts.load(path)


def test_generated_days_skip_the_closing_day(shop):
    assert all(day.weekday() != generate.CLOSED_WEEKDAY
               for day in shop["index"].units)


# ── nothing may reference a product that is not on the board ────────────────

def test_no_module_references_a_product_that_does_not_exist():
    """The failure this catches actually happened.

    Trimming the menu left the occasion tables, the demand table and the drift
    table pointing at products that were gone. Nothing raised: the calendar
    quietly stopped lifting anything, and the generator quietly stopped making
    it. A silent wrong answer, which is the kind this project exists to avoid.
    """
    from src.bakery.core import calendar as occasions
    from src.bakery.simulation import generate

    menu = {product.name for product in catalogue.PRODUCTS}

    for occasion in occasions.OCCASIONS:
        missing = [name for name in occasion.products if name not in menu]
        assert not missing, f"calendar: {occasion.name} wants {missing}"

    for name, _m, _d, _lead, _peak, items in generate.OCCASIONS:
        missing = [item for item in items if item not in menu]
        assert not missing, f"generator: {name} wants {missing}"

    assert not [k for k in generate.DRIFT if k not in menu], "stale drift key"
    assert not [k for k in generate.BASE_DEMAND if k not in menu], "stale demand key"
    assert not [p for p in menu if p not in generate.BASE_DEMAND],         "a product with no demand would never appear in generated trade"


# ── the journal ─────────────────────────────────────────────────────────────

def test_journal_survives_an_empty_file_and_a_torn_line(tmp_path):
    """It is written to at the end of every run, so it must never be the thing
    that breaks one."""
    from src.bakery.ops import journal

    path = str(tmp_path / "j.jsonl")
    assert journal.read(path) == [] and journal.summary(path)["runs"] == 0

    journal.record("nightly", "Planned tomorrow", path=path)
    journal.record("weekly", "Reviewed", spoke=True, cost_usd=0.004,
                   tool_calls=9, path=path)
    with open(path, "a", encoding="utf-8") as handle:
        handle.write('{"at": "half a line')          # a crash mid-write

    result = journal.summary(path)
    assert result["runs"] == 2 and result["spoke"] == 1
    assert result["cost_usd"] == 0.004


def test_journal_counts_back_from_the_last_run_not_the_wall_clock(tmp_path):
    """Runs are stamped in the shop's time. A dataset a few days behind must
    still show its week, or the page reports silence that never happened."""
    from datetime import datetime, timedelta
    from src.bakery.ops import journal

    path = str(tmp_path / "j.jsonl")
    old = datetime.now() - timedelta(days=90)
    for offset in range(4):
        journal.record("nightly", "Planned", path=path,
                       at=old + timedelta(days=offset))
    assert journal.summary(path, days=7)["runs"] == 4


def test_it_stays_quiet_on_an_ordinary_day(shop, tmp_path, monkeypatch):
    """The product claims it writes only when something needs a person. If it
    speaks every night that claim is false, and it is the central one."""
    from src.bakery.agent import runs
    from src.bakery.ops import state

    monkeypatch.setattr(journal_module(), "PATH", str(tmp_path / "j.jsonl"))
    monkeypatch.setattr(state, "get", lambda *a, **k: _Shop(shop))
    monkeypatch.setattr(state, "today", lambda: max(shop["index"].units))

    days = sorted(shop["index"].units)[-30:]
    spoke = sum(1 for day in days if runs.nightly(for_day=day)["speaks"])
    assert spoke < len(days) * 0.6, (
        f"spoke on {spoke} of {len(days)} nights, which is not restraint")
    assert spoke > 0, "never speaks at all, which is not useful either"


def journal_module():
    from src.bakery.ops import journal
    return journal


class _Shop:
    """Just enough of state.Shop for the runs to work off the test slice."""

    def __init__(self, shop):
        self.bills = shop["bills"]
        self.index = shop["index"]
        self.history, self.corrected = plan.corrected_history(
            shop["bills"], index=shop["index"])

    @property
    def days(self):
        return sorted(self.index.units)

    @property
    def demand_by_day(self):
        table = {}
        for item, days in self.history.items():
            for day, units in days.items():
                table.setdefault(day, {})[item] = units
        return table


def test_noticed_says_nothing_when_nothing_is_unusual(shop, tmp_path, monkeypatch):
    """A daily check that always finds something is a daily check nobody reads.

    It has to be able to return "everything sat inside its normal range", and
    it must not reach for the owner unless the move is big enough to be a
    decision rather than news.
    """
    from src.bakery.ops import journal, state
    from src.bakery.agent import runs

    monkeypatch.setattr(journal, "PATH", str(tmp_path / "j.jsonl"))
    monkeypatch.setattr(state, "get", lambda *a, **k: _Shop(shop))
    monkeypatch.setattr(state, "today", lambda: max(shop["index"].units))

    days = sorted(shop["index"].units)[-25:]
    spoke = 0
    for day in days:
        result = runs.noticed(for_day=day, log=False)
        assert result["lines"], f"{day} produced no output at all"
        for row in result["unusual"]:
            assert abs(row["change"]) >= runs.UNUSUAL_RATIO
            assert abs(row["units"] - row["usual"]) >= runs.UNUSUAL_UNITS
        spoke += bool(result["speaks"])
    assert spoke < len(days) * 0.5, (
        f"asked on {spoke} of {len(days)} days, which is not a check, it is a "
        f"nag")


def test_confirming_a_cost_changes_what_gets_baked(tmp_path):
    """The point of asking. If a confirmed cost did not move the plan there
    would be no reason to trouble the owner for it."""
    from src.bakery.core import plan

    product = catalogue.get("Croissant")
    before = plan.quantity(product, 100, 20)
    try:
        catalogue.confirm_cost("Croissant", product.cost * 1.6,
                               path=str(tmp_path / "c.json"))
        after = plan.quantity(catalogue.get("Croissant"), 100, 20)
        assert after < before, "a higher cost has to mean baking fewer"
        assert catalogue.get("Croissant").cost_given
        assert "Croissant" not in [g["item"] for g in catalogue.guessed_costs()]
    finally:
        catalogue.adopt([product if p.name == "Croissant" else p
                         for p in catalogue.PRODUCTS])


def test_a_cost_at_or_above_the_price_is_refused():
    with pytest.raises(ValueError, match="not below"):
        catalogue.confirm_cost("Croissant", 99.0)


# ── one shop per process, and one place its files live ──────────────────────

def test_every_store_lands_under_one_root(monkeypatch):
    """Six variables and two hard coded paths is not a configuration, it is a
    trap. One shop id has to move all of them together."""
    import importlib
    from src.bakery.ops import paths

    monkeypatch.setenv("SHOP_ID", "rue-des-lilas")
    monkeypatch.setenv("DATA_ROOT", "/srv/shops")
    for variable, _ in paths.STORES.values():
        monkeypatch.delenv(variable, raising=False)
    importlib.reload(paths)

    for name in paths.STORES:
        where = paths.of(name).replace("\\", "/")
        assert where.startswith("/srv/shops/rue-des-lilas/"), f"{name} -> {where}"

    monkeypatch.setenv("BILLS_FILE", "s3://till-exports/today.jsonl")
    importlib.reload(paths)
    assert paths.of("bills") == "s3://till-exports/today.jsonl", (
        "an explicit override has to still win, or a shop cannot keep its "
        "bills somewhere else")
    monkeypatch.delenv("SHOP_ID", raising=False)
    monkeypatch.delenv("DATA_ROOT", raising=False)
    monkeypatch.delenv("BILLS_FILE", raising=False)
    importlib.reload(paths)


def test_a_second_shop_in_one_process_is_refused():
    """The catalogue is a module global. A second bakery here would read the
    first one's menu and plan against it, and nothing about that looks wrong."""
    import importlib
    from src.bakery.ops import paths
    importlib.reload(paths)

    assert paths.only("first") == "first"
    assert paths.only("first") == "first", "the same shop twice is fine"
    with pytest.raises(RuntimeError, match="already serving"):
        paths.only("second")
    importlib.reload(paths)


# ── what arrives from the till ──────────────────────────────────────────────

def test_a_bill_sent_twice_is_counted_once(tmp_path):
    """Webhooks retry and adapters replay. Counting a bill twice inflates every
    figure downstream by a little, which is the worst size of error: large
    enough to matter, small enough to look plausible."""
    line = ('{"number":%d,"at":"2025-01-06T08:0%d:00","lines":'
            '[{"item":"Croissant","qty":2,"unit_price":1.30}]}')
    path = tmp_path / "bills.jsonl"
    path.write_text("\n".join([line % (1, 0), line % (2, 1), line % (2, 1),
                                line % (3, 2)]), encoding="utf-8")

    bills = receipts.load(path)
    assert len(bills) == 3, "the repeat was counted"
    assert receipts.intake_report()["duplicates"] == 1


def test_a_hole_in_the_numbering_is_reported(tmp_path):
    """A quiet day and a broken feed look identical after the fact. The gap is
    the only thing that tells them apart, and it has to be noticed on the way
    in or not at all."""
    line = ('{"number":%d,"at":"2025-01-06T08:00:00","lines":'
            '[{"item":"Croissant","qty":1,"unit_price":1.30}]}')
    path = tmp_path / "bills.jsonl"
    path.write_text("\n".join([line % 1, line % 2, line % 9]), encoding="utf-8")

    receipts.load(path)
    report = receipts.intake_report()
    assert report["gaps"] == [(2, 9)]
    assert report["missing"] == 6


def test_a_shop_it_has_never_seen_still_loads(tmp_path):
    """The question this answers: what happens when a real bakery plugs in.

    Nothing called learn() outside the tests, so the whole system only ever
    worked on the demo menu. A real till's first bill hit "not on the menu" and
    nothing loaded at all. The menu has to come off the receipts.

    Exercised through the two functions that changed rather than through
    ``state.get``, because that caches a shop process wide and a test that
    leaves a fictional bakery in it breaks every test after it.
    """
    import json
    import random
    from src.bakery.ops import state

    menu = {"Pain au chocolat": 1.40, "Kouign amann": 3.60, "Flat white": 3.20}
    random.seed(3)
    rows, number = [], 0
    for day in range(1, 15):
        for _ in range(40):
            number += 1
            item = random.choice(list(menu))
            rows.append({"number": number,
                         "at": f"2026-08-{day:02d}T{random.randint(7, 18):02d}:"
                               f"{random.randint(0, 59):02d}:00",
                         "lines": [{"item": item, "qty": random.randint(1, 3),
                                    "unit_price": menu[item]}]})
    path = tmp_path / "real.jsonl"
    path.write_text(NEWLINE.join(json.dumps(r) for r in rows), encoding="utf-8")

    # The first read cannot validate, because there is no menu yet. That is the
    # whole chicken and egg this fixes.
    with pytest.raises(KeyError, match="not on the menu"):
        receipts.load(path)
    bills = receipts.load(path, validate=False)
    assert len(bills) == 560

    held = list(catalogue.PRODUCTS)
    try:
        learned = state._learn_menu_if_new(bills)
        assert set(learned) == set(menu), f"derived {learned}"
        for product in catalogue.PRODUCTS:
            assert product.price == menu[product.name], "price comes off the bill"
            assert 0 < product.cost < product.price
            assert not product.cost_given, "a derived cost is a guess, and says so"
        receipts.load(path)          # now it validates, because there is a menu
    finally:
        catalogue.adopt(held)


def test_a_menu_it_already_knows_is_not_relearned(shop):
    """Relearning would flatten oven times, shelf lives and salvage values that
    no receipt can carry, so it only happens when the bills are genuinely from
    somewhere else."""
    from src.bakery.ops import state

    held = {p.name: p for p in catalogue.PRODUCTS}
    changed = state._learn_menu_if_new(shop["bills"])
    assert changed == [], "the demo menu was replaced by a derived one"
    assert {p.name: p for p in catalogue.PRODUCTS} == held


def test_a_cached_shop_still_learns_new_menu(tmp_path, monkeypatch):
    """When state is restored from a pickle cache, the menu must be adopted so
    downstream catalogue.get() calls don't crash with KeyError."""
    import json
    import pickle
    from src.bakery.ops import state

    menu = {"Focaccia": 3.50, "Espresso": 2.00}
    rows = [
        {"number": 1, "at": "2026-08-01T08:00:00",
         "lines": [{"item": "Focaccia", "qty": 1, "unit_price": 3.50}]},
        {"number": 2, "at": "2026-08-01T08:30:00",
         "lines": [{"item": "Espresso", "qty": 1, "unit_price": 2.00}]},
    ]
    bills_file = tmp_path / "bills.jsonl"
    bills_file.write_text(NEWLINE.join(json.dumps(r) for r in rows), encoding="utf-8")
    cache_file = tmp_path / "cache.pkl"

    bills = receipts.load(bills_file, validate=False)
    index = analytics.Index(bills)
    history = {"Focaccia": {date(2026, 8, 1): 1}, "Espresso": {date(2026, 8, 1): 1}}
    stamp = bills_file.stat().st_mtime

    with open(cache_file, "wb") as h:
        pickle.dump({"source": str(bills_file), "stamp": stamp, "bills": bills,
                     "index": index, "history": history, "corrected": {}}, h)

    monkeypatch.setattr(state, "BILLS", str(bills_file))
    monkeypatch.setattr(state, "CACHE", str(cache_file))
    monkeypatch.setattr(state, "_state", None)

    held = list(catalogue.PRODUCTS)
    try:
        loaded = state.get(str(bills_file))
        assert "Focaccia" in catalogue.BY_NAME
        assert "Espresso" in catalogue.BY_NAME
        assert catalogue.get("Focaccia").price == 3.50
    finally:
        catalogue.adopt(held)
        state._state = None



# ── the gate on irreversible actions ────────────────────────────────────────

class _Call:
    """Just enough of a tool call event for the hook to read."""

    def __init__(self, name):
        self.tool_use = {"name": name}
        self.cancel = None


def test_the_agent_can_actually_send_the_one_thing_it_exists_to_send():
    """This was broken and nothing could see it.

    The gate required an entry in ``approvals`` that no caller ever supplied,
    so notify_owner was cancelled every single time. The product's whole claim
    is that it emails the owner when a decision is needed, and it could not.
    It stayed invisible because no model had ever run.
    """
    from src.bakery.agent import agent

    ledger = agent.Ledger()
    first = _Call("notify_owner")
    ledger.before_tool(first)
    assert first.cancel is None, "it still cannot email anyone"
    assert ledger.report()["notified"] == 1


def test_the_same_decision_is_not_sent_twice():
    """The second send is the dangerous one. One is the point, not zero."""
    from src.bakery.agent import agent

    ledger = agent.Ledger()
    calls = [_Call("notify_owner") for _ in range(3)]
    for call in calls:
        ledger.before_tool(call)

    assert calls[0].cancel is None
    assert calls[1].cancel and "twice" in calls[1].cancel
    assert calls[2].cancel
    assert ledger.report()["notified"] == 1, (
        "a blocked attempt was counted as a message sent, which is the exact "
        "lie the counter exists to prevent")


def test_a_run_that_needs_two_messages_can_be_allowed_two():
    from src.bakery.agent import agent

    ledger = agent.Ledger(approvals={"notify_owner": 2})
    calls = [_Call("notify_owner") for _ in range(3)]
    for call in calls:
        ledger.before_tool(call)
    assert calls[0].cancel is None and calls[1].cancel is None
    assert calls[2].cancel
    assert ledger.report()["notified"] == 2


def test_reading_tools_are_never_gated():
    """Only irreversible things are gated. Reading the shop twenty times is
    wasteful, which the call ceiling handles, not dangerous."""
    from src.bakery.agent import agent

    ledger = agent.Ledger()
    for _ in range(5):
        call = _Call("day_report")
        ledger.before_tool(call)
        assert call.cancel is None
    assert ledger.report()["notified"] == 0
