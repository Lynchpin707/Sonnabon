"""What happens when the clock goes off.

Nobody opens this. EventBridge invokes a run, the run does the work, and the
owner hears about it only if there is something worth hearing. The ratio between
how often this fires and how often it writes to them is the product.

Every run works with or without a model. The tools produce all the substance;
the model decides what matters and how to say it. Without one you still get a
correct briefing, just a blunter one, which means the whole thing is testable and
demonstrable before any credentials exist.
"""

from datetime import datetime, time, timedelta

from . import calendar as occasions, catalogue, journal, state, tools
from .journal import TRIGGERS

# A day's shortfall worth mentioning. Below this the owner does not need an
# email about it, and an agent that writes every evening is one that gets
# filtered within a week.
WORTH_MENTIONING = 40.0

# A flat threshold is not enough on its own. Every shop that sells out at all
# clears a fixed figure most days, so a flat rule means it writes every night,
# which is the behaviour this product exists to avoid. A day earns an email by
# being bad *for this shop*, so the bar is set from the shop's own recent days.
UNUSUAL_QUANTILE = 0.80


def _unusual_loss(days_back=28):
    """What a bad day looks like here, in money.

    Returns the loss a day has to beat to be worth an email. Falls back to the
    flat threshold when there is not enough history to say, which is the honest
    answer for a shop three weeks old rather than a silent zero that would make
    it write every night.
    """
    shop = state.get()
    end = state.today()
    window = [day for day in shop.days if (end - day).days <= days_back]
    if len(window) < 10:
        return WORTH_MENTIONING

    from . import analytics
    priced = analytics.lost_to_sellouts(shop.bills, days=window,
                                        index=shop.index)
    per_day = {}
    for row in priced["rows"]:
        if row["confidence"] in ("good", "fair"):
            per_day[row["day"]] = per_day.get(row["day"], 0.0) + row["lost_margin"]
    losses = sorted(per_day.get(day, 0.0) for day in window)
    if not losses:
        return WORTH_MENTIONING
    cut = losses[min(len(losses) - 1, int(len(losses) * UNUSUAL_QUANTILE))]
    return max(WORTH_MENTIONING, cut)


def _money(value):
    return f"{catalogue.CURRENCY}{value:,.0f}"


def nightly(for_day=None, at=None, log=True):
    """Close of trade. Read the day, plan tomorrow, decide whether to speak.

    ``at`` stamps the journal with the evening the run belongs to rather than
    the moment it executed, so replaying a past week reads as a week.

    ``log`` is off when a page is merely rendering what the last run concluded.
    Opening the dashboard is not the agent waking up, and counting it as one
    would inflate the single number the product is judged on.
    """
    today = state.today() if for_day is None else for_day
    yesterday = tools.day_report(today.isoformat())
    plan = tools.bake_plan((today + timedelta(days=1)).isoformat())
    due = tools.whats_coming(45)

    lines, asks = [], []
    bar = _unusual_loss()

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

    # A late task is worth one email, not one a night. Once it has been raised
    # the person has been told, and telling them again tomorrow is nagging.
    key = None
    overdue = [row for row in due["tasks_due"] if row["overdue"]]
    if overdue:
        first = overdue[0]
        key = f"overdue:{first['occasion']}:{first['due']}"
        if not journal.already_said(key, within_days=7,
                                    now=datetime.combine(today, time(21, 30))):
            asks.append(f"{first['occasion']}: {first['what'].lower()} was due "
                        f"{first['due']} and has not happened.")
        else:
            key = None

    result = {
        "kind": "nightly",
        "day": today.isoformat(),
        "lost_margin": yesterday.get("lost_margin", 0),
        "sold_out": yesterday.get("sold_out", []),
        "plan": plan,
        "lines": lines,
        "asks": asks,
        # It speaks for a late task, or for a day that was bad by this shop's
        # own standard. An ordinary bad day is handled by raising tomorrow's
        # numbers, which is what it is for.
        "speaks": bool(asks) or yesterday.get("lost_margin", 0) >= bar,
        "bar": round(bar, 2),
    }
    if log:
        journal.record("nightly", f"Read {today.isoformat()} and set "
                                  f"tomorrow's bake",
                       figure=f"{plan['units']:,} units",
                       spoke=result["speaks"], detail=asks[:1] or None, at=at,
                       key=key)
    return result


def weekly(log=True):
    """The wider look: what is moving, what is coming, what is worth doing.

    ``log`` is off when a page is rendering rather than the clock firing. See
    :func:`nightly`.
    """
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
        if row.get("lift_source") == "measured":
            where = (f"your own tills put {products} at {row['lift']}x last time")
        else:
            # No past occurrence on file. Say that, rather than quoting a
            # number from a table as though it came from this shop.
            where = (f"you have no {row['occasion']} on file yet, so this "
                     f"assumes {products} lift about {row['lift']}x")
        asks.append(f"{row['occasion']} is {row['days_away']} days away and "
                    f"{where}. Shall I put it on the plan?")

    result = {
        "kind": "weekly",
        "day": state.today().isoformat(),
        "trends": trends,
        "best_sellers": sellers,
        "lost": lost,
        "ahead": ahead,
        "lines": lines,
        "asks": asks,
        # A weekly with nothing moving, nothing late and nothing close on the
        # calendar is a weekly the owner does not need to read.
        "speaks": bool(asks) or bool(trends["growing"] or trends["declining"])
                  or ahead["overdue"] > 0,
    }
    if log:
        moving = len(trends["growing"]) + len(trends["declining"])
        journal.record("weekly", f"Reviewed the week: {moving} products "
                                 f"moving, {ahead['overdue']} run-up tasks late",
                       figure=(f"{sellers['by_units'][0]} top"
                               if sellers.get("by_units") else None),
                       spoke=result["speaks"], detail=asks[:1] or None)
    return result


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
    report = ledger.report()

    # The agent decides for itself whether to reach the owner, so the journal
    # reads the outbox rather than guessing: a run that sent nothing did not
    # speak, whatever its closing paragraph sounds like.
    journal.record(run_kind, _first_sentence(str(result)),
                   spoke=report.get("notified", 0) > 0,
                   why=f"{TRIGGERS.get(run_kind, run_kind)}, with the model",
                   cost_usd=report.get("cost_usd", 0.0),
                   tool_calls=report.get("tool_calls", 0))
    return {"kind": run_kind, "said": str(result), "ledger": report}


def _first_sentence(text, limit=140):
    """What the agent led with. The journal is a list, not a transcript, and a
    full answer pasted into a row makes the list unreadable."""
    clean = " ".join(text.split())
    if not clean:
        return "Ran and found nothing worth saying"
    stop = clean.find(". ")
    if 0 < stop < limit:
        return clean[:stop + 1].rstrip(".")
    return clean[:limit].rstrip() + ("..." if len(clean) > limit else "")


def catch_up(days=7, path=None):
    """Replay the last week of closings so the diary has a week in it.

    This is not a fixture. Each entry is a real run over that day's real trade,
    stamped with the evening it belongs to, so what the diary shows is what the
    agent would have written had it been switched on a week earlier.
    """
    from datetime import datetime, time

    shop = state.get()
    today = state.today()
    window = [day for day in shop.days if 0 < (today - day).days <= days]
    written = []
    for day in window:
        result = nightly(for_day=day,
                         at=datetime.combine(day, time(21, 30)))
        written.append(result)
    return {"nights": len(written),
            "spoke": sum(1 for row in written if row["speaks"])}
