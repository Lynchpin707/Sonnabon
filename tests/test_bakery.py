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

from src.bakery import analytics, calendar, catalogue, generate, plan, receipts


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
    from src.bakery import calendar as occasions, generate

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
    from src.bakery import journal

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
    from src.bakery import journal

    path = str(tmp_path / "j.jsonl")
    old = datetime.now() - timedelta(days=90)
    for offset in range(4):
        journal.record("nightly", "Planned", path=path,
                       at=old + timedelta(days=offset))
    assert journal.summary(path, days=7)["runs"] == 4


def test_it_stays_quiet_on_an_ordinary_day(shop, tmp_path, monkeypatch):
    """The product claims it writes only when something needs a person. If it
    speaks every night that claim is false, and it is the central one."""
    from src.bakery import runs, state

    monkeypatch.setattr(journal_module(), "PATH", str(tmp_path / "j.jsonl"))
    monkeypatch.setattr(state, "get", lambda *a, **k: _Shop(shop))
    monkeypatch.setattr(state, "today", lambda: max(shop["index"].units))

    days = sorted(shop["index"].units)[-30:]
    spoke = sum(1 for day in days if runs.nightly(for_day=day)["speaks"])
    assert spoke < len(days) * 0.6, (
        f"spoke on {spoke} of {len(days)} nights, which is not restraint")
    assert spoke > 0, "never speaks at all, which is not useful either"


def journal_module():
    from src.bakery import journal
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
