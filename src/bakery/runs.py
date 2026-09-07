"""What happens when the clock goes off.

Nobody opens this. EventBridge invokes a run, the run does the work, and the
owner hears about it only if there is something worth hearing. The ratio between
how often this fires and how often it writes to them is the product.

Every run works with or without a model. The tools produce all the substance;
the model decides what matters and how to say it. Without one you still get a
correct briefing, just a blunter one, which means the whole thing is testable and
demonstrable before any credentials exist.
"""

from datetime import timedelta

from . import calendar as occasions, catalogue, state, tools

# A day's shortfall worth mentioning. Below this the owner does not need an
# email about it, and an agent that writes every evening is one that gets
# filtered within a week.
WORTH_MENTIONING = 40.0


def _money(value):
    return f"{catalogue.CURRENCY}{value:,.0f}"


def nightly(for_day=None):
    """Close of trade. Read the day, plan tomorrow, decide whether to speak."""
    today = state.today() if for_day is None else for_day
    yesterday = tools.day_report(today.isoformat())
    plan = tools.bake_plan((today + timedelta(days=1)).isoformat())
    due = tools.whats_coming(45)

    lines, asks = [], []

    if yesterday.get("trading"):
        lines.append(
            f"{yesterday['weekday']}: {yesterday['customers']} customers, "
            f"{_money(yesterday['revenue'])} taken.")

        gone = [row for row in yesterday["sold_out"]
                if row["confidence"] in ("good", "fair")]
        if yesterday["lost_margin"] >= WORTH_MENTIONING:
            worst = gone[0]
            lines.append(
                f"You ran out of {worst['item'].lower()} at "
                f"{worst['sold_out_at']}. About {worst['estimate']} people "
                f"wanted one and {worst['sold']} got one. Across everything "
                f"that ran out, {_money(yesterday['lost_margin'])} of margin "
                f"walked out. I have raised tomorrow's numbers.")

    lines.append(f"Tomorrow: {plan['units']} units across "
                 f"{len(plan['rows'])} lines, list is with the team.")

    overdue = [row for row in due["tasks_due"] if row["overdue"]]
    if overdue:
        first = overdue[0]
        asks.append(f"{first['occasion']}: {first['what'].lower()} was due "
                    f"{first['due']} and has not happened.")

    return {
        "kind": "nightly",
        "day": today.isoformat(),
        "lost_margin": yesterday.get("lost_margin", 0),
        "sold_out": yesterday.get("sold_out", []),
        "plan": plan,
        "lines": lines,
        "asks": asks,
        "speaks": bool(asks) or yesterday.get("lost_margin", 0) >= WORTH_MENTIONING,
    }


def weekly():
    """The wider look: what is moving, what is coming, what is worth doing."""
    trends = tools.product_trends(40)
    sellers = tools.best_sellers(4)
    lost = tools.lost_to_sellouts(4)
    ahead = tools.whats_coming(60)

    lines, asks = [], []

    if sellers["by_units"] and sellers["by_money_kept"]:
        top_units, top_kept = sellers["by_units"][0], sellers["by_money_kept"][0]
        if top_units != top_kept:
            lines.append(
                f"Your best seller is the {top_units.lower()}. The thing "
                f"actually paying the rent is the {top_kept.lower()}.")

    for row in trends["growing"][:2]:
        # Only claim the till was hiding it if the correction actually moved
        # this product. Asserting it for everything is the kind of confident
        # detail that gets checked once and never believed again.
        hidden = any(entry["item"] == row["item"]
                     for entry in lost.get("rows", []))
        because = (" It runs out often, so the till has been under-reporting it."
                   if hidden else "")
        lines.append(f"{row['item']} is growing, {row['change']} over "
                     f"{row['weeks_used']} weeks.{because}")
    for row in trends["declining"][:2]:
        lines.append(f"{row['item']} is down {row['change']} and it is not "
                     f"noise. Worth deciding whether it keeps its place.")

    if lost["lost_margin"] >= WORTH_MENTIONING:
        lines.append(f"Running out cost about {_money(lost['lost_margin'])} "
                     f"in the last four weeks.")

    for row in ahead["occasions"][:1]:
        products = ", ".join(row["products"][:3]).lower()
        asks.append(
            f"{row['occasion']} is {row['days_away']} days away and normally "
            f"lifts {products} by about {row['peak_multiplier']}x. Shall I put "
            f"it on the plan?")

    return {
        "kind": "weekly",
        "day": state.today().isoformat(),
        "trends": trends,
        "best_sellers": sellers,
        "lost": lost,
        "ahead": ahead,
        "lines": lines,
        "asks": asks,
        "speaks": True,
    }


def with_agent(run_kind, model=None, watch=None, prompt=None):
    """Hand the run to the agent and let it decide and write.

    The scripted runs above are correct but blunt. This is the same work with
    judgement on top: which of today's facts matter, what to do about them, and
    whether any of it is worth the owner's attention.
    """
    from . import agent

    tasks = {
        "nightly": ("The shop has closed. Read yesterday, decide tomorrow's "
                    "production, check whether anything on the calendar is due, "
                    "and email the owner only if something genuinely needs them."),
        "weekly": ("Weekly review. What is growing, what is dying, what running "
                   "out has cost, and what is coming on the calendar. Bring the "
                   "owner one recommendation, not a list."),
    }
    task = prompt or tasks.get(run_kind)
    if not task:
        raise ValueError(f"{run_kind!r} is not a run. Use {sorted(tasks)}, "
                         "or pass a prompt of your own.")

    built, ledger = agent.build(model=model, watch=watch)
    result = built(task)
    return {"kind": run_kind, "said": str(result), "ledger": ledger.report()}
