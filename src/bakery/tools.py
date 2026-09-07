"""What the agent can actually do.

Every function here is a Strands tool. Two rules govern all of them, and both
exist for the same reason:

    Return summaries, never rows. The shop has 158,000 bills. Reading them into
    a model's context would cost more than the waste it is trying to prevent and
    would not fit in any case. Tools hand back tens of numbers, not thousands.

    Return the working, not just the answer. Every estimate carries its
    confidence and the evidence behind it, so the agent can say "about 78, and
    here is why" instead of inventing certainty it does not have.

``run_python`` is the escape hatch. Anything not covered by a named tool, the
agent writes itself and executes against the data. Locally that runs in-process;
on AgentCore it becomes the sandboxed Code Interpreter and nothing else changes.
"""

import io
import json
import os
import traceback
from contextlib import redirect_stdout
from datetime import date, datetime, timedelta

from strands import tool

from . import paths, analytics, calendar as bakery_calendar, catalogue, plan, state


def _day(value):
    """Accept a date, an ISO string, or nothing (meaning the shop's last day)."""
    if value is None:
        return state.today()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


@tool
def shop_status() -> dict:
    """What data the shop has, and what is on the menu.

    Call this first in any run. It is the cheapest way to find out what period
    is covered and whether anything is still missing a cost.
    """
    shop = state.get()
    return {**shop.summary(),
            "menu": [product.name for product in catalogue.PRODUCTS],
            "needs_costs": catalogue.unpriced(),
            "costs_i_guessed": catalogue.guessed_costs(),
            "currency": catalogue.CURRENCY}


@tool
def day_report(on: str = None) -> dict:
    """What happened on one day: takings, customers, and what ran out.

    The sell-out section is the part a till cannot produce. Each entry carries
    an estimate of what demand really was, the confidence in it, and the margin
    that walked out of the door.
    """
    day = _day(on)
    shop = state.get()
    units = shop.index.units.get(day, {})
    if not units:
        return {"day": day.isoformat(), "trading": False,
                "note": "no bills on this day, the shop was closed"}

    sellouts = [row for row in shop.index.sellouts() if row["day"] == day]
    priced = []
    for row in sellouts:
        curve, _ = shop.index.curve(row["item"],
                                    shop.index.sellout_days(row["item"]))
        estimate = analytics.estimate_true_demand(shop.bills, day, row["item"],
                                                  curve=curve, index=shop.index)
        if estimate["confidence"] != "none":
            priced.append(estimate)

    people = analytics.customers(shop.bills, days=[day])
    revenue = sum(units.get(product.name, 0) * product.price
                  for product in catalogue.PRODUCTS)
    return {
        "day": day.isoformat(),
        "weekday": day.strftime("%A"),
        "trading": True,
        "customers": people.get("total", 0),
        "average_basket": people.get("average_basket"),
        "revenue": round(revenue, 2),
        "units_sold": sum(units.values()),
        "sold_out": sorted(priced, key=lambda row: -row["lost_margin"]),
        "lost_margin": round(sum(row["lost_margin"] for row in priced
                                 if row["confidence"] in ("good", "fair")), 2),
    }


@tool
def todays_sales(on: str = None) -> dict:
    """Every product sold on one day, with the ones that ran out marked.

    The plainest view there is: how many of each thing left the shelf, how many
    people came in, what the till took. The only thing added is the flag for a
    product whose tray emptied, because that is the one number on the page that
    is not what it appears to be.
    """
    day = _day(on)
    shop = state.get()
    units = shop.index.units.get(day, {})
    if not units:
        return {"day": day.isoformat(), "trading": False, "rows": []}

    gone = {row["item"]: row for row in shop.index.sellouts() if row["day"] == day}
    rows = []
    for product in catalogue.PRODUCTS:
        sold = units.get(product.name, 0)
        if not sold:
            continue
        out = gone.get(product.name)
        estimate = None
        if out:
            curve, _ = shop.index.curve(product.name,
                                        shop.index.sellout_days(product.name))
            guess = analytics.estimate_true_demand(shop.bills, day, product.name,
                                                   curve=curve, index=shop.index)
            if guess["confidence"] in ("good", "fair"):
                estimate = guess["estimate"]
        rows.append({
            "item": product.name,
            "sold": sold,
            "revenue": round(sold * product.price, 2),
            "kept": round(sold * product.margin, 2),
            "ran_out": bool(out),
            "ran_out_at": (shop.index.last[day][product.name].strftime("%H:%M")
                           if out else None),
            "wanted": estimate,
        })

    people = analytics.customers(shop.bills, days=[day])
    rows.sort(key=lambda row: -row["sold"])
    return {
        "day": day.isoformat(), "weekday": day.strftime("%A"), "trading": True,
        "customers": people.get("total", 0),
        "average_basket": people.get("average_basket"),
        "revenue": round(sum(row["revenue"] for row in rows), 2),
        "units": sum(row["sold"] for row in rows),
        "ran_out": sum(1 for row in rows if row["ran_out"]),
        "rows": rows,
    }


@tool
def sample_bills(on: str = None, limit: int = 15, around: str = None) -> dict:
    """A handful of actual receipts, for when a summary is not enough.

    The summaries answer almost everything and cost almost nothing. Occasionally
    they do not: what people buy together, whether a run of sales was one party
    or twenty customers, what an odd hour actually looked like. For that you
    have to see the real thing.

    So this returns a sample, never the day. One day of this shop is about
    31,000 tokens and a week is 196,000, which is more than the context holds
    and more than a month of running the agent costs. Fifteen bills is about
    500 tokens and answers the question.

    ``around`` narrows to a time, as "14:00", which is usually what you want:
    look at the hour that was strange rather than at the day.
    """
    day = _day(on)
    shop = state.get()
    rows = [bill for bill in shop.bills if bill.day == day]
    if not rows:
        return {"day": day.isoformat(), "trading": False, "bills": []}

    if around:
        target = datetime.strptime(around[:5], "%H:%M").time()
        rows.sort(key=lambda bill: abs(
            (bill.at.hour * 60 + bill.at.minute)
            - (target.hour * 60 + target.minute)))
    else:
        # Spread across the day rather than the first fifteen at opening, or
        # every sample looks like the morning rush.
        step = max(1, len(rows) // max(limit, 1))
        rows = rows[::step]

    limit = max(1, min(limit, 40))
    return {
        "day": day.isoformat(),
        "trading": True,
        "showing": min(limit, len(rows)),
        "of_total": len([b for b in shop.bills if b.day == day]),
        "note": ("A sample, not the day. Ask for a different time with "
                 "'around', or use run_python to work over all of them."),
        "bills": [{"at": bill.at.strftime("%H:%M"),
                   "total": bill.total,
                   "payment": bill.payment,
                   "items": {line.item: line.qty for line in bill.lines}}
                  for bill in sorted(rows[:limit], key=lambda b: b.at)],
    }


@tool
def bake_plan(for_day: str = None, oven_minutes: float = None) -> dict:
    """How much of each thing to make, and why that number.

    Built on demand corrected for days the shop ran out, so it does not inherit
    last year's shortfall. Each row carries the service level that product's own
    economics ask for: a cookie worth little when binned is made past the point
    of certainty, and a cheesecake worth nothing the next day is not.
    """
    shop = state.get()
    day = _day(for_day) if for_day else state.today() + timedelta(days=1)
    result = plan.bake_plan(shop.bills, day, index=shop.index,
                            history=shop.history, oven_minutes=oven_minutes)
    result["day"] = result["day"].isoformat()
    for row in result["rows"]:
        row.pop("margin_per_oven_minute", None)
    return result


@tool
def best_sellers(weeks: int = 4) -> dict:
    """Three rankings, because the two an owner uses are both misleading.

    Units finds whatever is cheapest and revenue finds whatever is dearest.
    Money kept, revenue less what it cost to make, is the one that says which
    products are actually holding the shop up, and it disagrees with both.

    Drinks are left out. Coffee outsells everything and is not a thing anybody
    decides how much of to make, so including it buries the answer.
    """
    shop = state.get()
    end = state.today()
    start = end - timedelta(weeks=weeks)
    days = [day for day in shop.days if start <= day <= end]
    result = analytics.best_sellers(shop.bills, days=days, top=5)
    result["period"] = {"from": start.isoformat(), "to": end.isoformat(),
                        "trading_days": len(days)}
    return result


@tool
def trade_summary(weeks: int = 4) -> dict:
    """Customers, baskets and the shape of the week."""
    shop = state.get()
    end = state.today()
    start = end - timedelta(weeks=weeks)
    days = [day for day in shop.days if start <= day <= end]
    people = analytics.customers(shop.bills, days=days)
    people["busiest"] = people["busiest"].isoformat() if people.get("busiest") else None
    people["quietest"] = people["quietest"].isoformat() if people.get("quietest") else None
    return {"period": {"from": start.isoformat(), "to": end.isoformat()},
            "customers": people,
            "units_by_weekday": analytics.day_of_week_shape(shop.bills)}


@tool
def lost_to_sellouts(weeks: int = 4) -> dict:
    """The money that walked out because something had run out.

    This is the figure no till can produce and no owner has seen. Rows the
    method is not confident about are reported separately rather than folded
    into the headline.
    """
    shop = state.get()
    end = state.today()
    start = end - timedelta(weeks=weeks)
    days = [day for day in shop.days if start <= day <= end]
    result = analytics.lost_to_sellouts(shop.bills, days=days,
                                        index=shop.index)
    result["rows"] = [{**row, "day": row["day"].isoformat()}
                      for row in result["rows"][:12]]
    result["period"] = {"from": start.isoformat(), "to": end.isoformat()}
    return result


@tool
def product_trends(weeks: int = 40) -> dict:
    """Which products are growing, which are dying, and which are just noise.

    Run on demand corrected for sell-outs, which matters more here than
    anywhere: a product that is catching on runs out more often as it grows, so
    the till records less and less of the growth. Measured on raw sales, a
    product that genuinely doubled can look flat, and one that never moved can
    look like it is dying.

    Weeks an occasion was pulling on are left out of the fit, or every Christmas
    reads as growth and every January as collapse.
    """
    shop = state.get()
    result = analytics.trends(shop.bills, weeks=weeks, index=shop.index,
                              history=shop.history)
    return {"window_weeks": weeks,
            "growing": result["growing"],
            "declining": result["declining"],
            "flat": result["flat"],
            "note": ("Corrected for sell-outs before fitting. Flat means the "
                     "movement is inside the week-to-week noise, not that "
                     "nothing changed.")}


@tool
def whats_coming(within_days: int = 60) -> dict:
    """Occasions ahead, and every preparation task now due or already late.

    Lead time is the whole point. Christmas surfaced in December is a warning;
    surfaced in October it is a decision that can still be made.
    """
    today = state.today()
    shop = state.get()
    tasks = bakery_calendar.whats_due(today)

    occasions = []
    for row in bakery_calendar.upcoming(today, within_days):
        row = {**row, "date": row["date"].isoformat()}
        # What this shop actually did last time beats what the table assumes.
        seen = bakery_calendar.observed_lift(shop.demand_by_day, row["occasion"],
                                             row["products"])
        if seen:
            row["lift"] = seen["peak_multiplier"]
            row["lift_source"] = "measured"
            row["lift_detail"] = seen["products"]
            row["assumed_lift"] = row["peak_multiplier"]
        else:
            row["lift"] = row["peak_multiplier"]
            row["lift_source"] = "assumed"
        occasions.append(row)

    return {
        "today": today.isoformat(),
        "occasions": occasions,
        "tasks_due": [{**row, "due": row["due"].isoformat()} for row in tasks],
        "overdue": sum(1 for row in tasks if row["overdue"]),
    }


@tool
def occasion_plan(occasion: str) -> dict:
    """The backward schedule for one occasion, with what is already late."""
    today = state.today()
    result = bakery_calendar.schedule(occasion, today)
    result["date"] = result["date"].isoformat()
    result["tasks"] = [{**row, "due": row["due"].isoformat()}
                       for row in result["tasks"]]
    return result


# Imports the agent is allowed inside run_python. Anything else, including os,
# subprocess, socket and pathlib, raises. The agent has no business touching the
# filesystem: everything it needs is already in the namespace.
ALLOWED_IMPORTS = {"math", "statistics", "json", "datetime", "collections",
                   "itertools", "functools", "random", "re"}


def _guarded_import(name, *args, **kwargs):
    root = name.split(".")[0]
    if root not in ALLOWED_IMPORTS:
        raise ImportError(
            f"{name} is not available here. Allowed: "
            f"{', '.join(sorted(ALLOWED_IMPORTS))}. The shop data is already "
            "in the namespace, so there is nothing to load."
        )
    return __import__(name, *args, **kwargs)


@tool
def run_python(code: str) -> dict:
    """Run Python against the shop's data and return what it prints.

    Use this for anything the named tools do not cover. Already in scope:

        shop      the loaded shop (bills, index, history, corrected)
        catalogue the menu, with price, cost, bake_minutes, salvage
        analytics sell-out detection, demand estimation, rankings
        plan      forecasting and the bake plan
        calendar  occasions and their lead times

    Print what you want back. Nothing is returned implicitly, and output is
    truncated, so summarise rather than dumping rows.
    """
    shop = state.get()
    safe_builtins = {name: getattr(__builtins__, name, None)
                     if not isinstance(__builtins__, dict)
                     else __builtins__.get(name)
                     for name in (
                         "abs", "all", "any", "bool", "dict", "divmod",
                         "enumerate", "filter", "float", "format", "int", "len",
                         "list", "map", "max", "min", "print", "range", "round",
                         "set", "sorted", "str", "sum", "tuple", "zip",
                         "isinstance", "getattr", "hasattr", "repr", "type",
                         "True", "False", "None", "Exception", "ValueError",
                         "KeyError", "ZeroDivisionError")}
    safe_builtins["__import__"] = _guarded_import

    namespace = {
        "__builtins__": safe_builtins,
        "shop": shop, "bills": shop.bills, "index": shop.index,
        "history": shop.history, "corrected": shop.corrected,
        "catalogue": catalogue, "analytics": analytics, "plan": plan,
        "calendar": bakery_calendar,
        "date": date, "timedelta": timedelta, "json": json,
    }
    buffer = io.StringIO()
    try:
        with redirect_stdout(buffer):
            exec(code, namespace)
    except Exception:
        return {"ok": False, "output": buffer.getvalue()[-2000:],
                "error": traceback.format_exc(limit=2)}
    output = buffer.getvalue()
    return {"ok": True, "output": output[:4000],
            "truncated": len(output) > 4000}


@tool
def find_local_events(query: str, near: str = None) -> dict:
    """Search the web for markets, fairs and food events worth a stall.

    Looks for the things that actually decide whether to go: the date, the
    application deadline, the stall fee, and what attendance was last year. An
    organiser's own attendance claim and what people reported afterwards are
    different numbers, so both are worth having.
    """
    town = near or os.getenv("SHOP_TOWN", "")
    terms = f"{query} {town}".strip()
    key = os.getenv("TAVILY_API_KEY")
    if not key:
        return {"ok": False, "searched": terms,
                "note": ("No web search configured. Set TAVILY_API_KEY to let "
                         "me look this up. Ask the owner for the event details "
                         "instead of guessing them.")}
    try:
        from strands_tools import tavily
        return {"ok": True, "searched": terms,
                "results": tavily.tavily_search(query=terms, max_results=5)}
    except Exception as error:
        return {"ok": False, "searched": terms, "error": str(error)}


@tool
def notify_owner(subject: str, body: str, urgency: str = "normal",
                 default_action: str = None, answer_by: str = None) -> dict:
    """Reach the owner by email. Use this sparingly.

    Every message costs the owner attention, which is the thing this job exists
    to protect. Send when something was decided that they should know about, or
    when a decision genuinely needs them. Never send a status update.

    ``urgency`` is "normal" or "decision". A decision needs ``default_action``
    and ``answer_by``: what you will do if nobody replies, and when you will do
    it. A question with no default stalls the shop the first time the owner is
    too busy to read email, which is most days.
    """
    to = os.getenv("OWNER_EMAIL")
    record = {"to": to, "subject": subject, "urgency": urgency,
              "sent_at": datetime.now().isoformat(timespec="seconds")}

    if urgency == "decision" and not (default_action and answer_by):
        return {**record, "ok": False,
                "error": ("A decision needs default_action and answer_by. Say "
                          "what you will do if nobody replies, and by when.")}

    if default_action:
        body = (f"{body}\n\nIf I do not hear back by {answer_by}, "
                f"I will {default_action}.")

    if not to or not os.getenv("SES_FROM"):
        # Nothing is configured, so write it where the interface can show it.
        # Silently dropping a message the agent believes it sent is worse than
        # not sending one.
        os.makedirs("data", exist_ok=True)
        outbox = paths.of("outbox")
        paths.ensure()
        with open(outbox, "a", encoding="utf-8") as handle:
            handle.write(json.dumps({**record, "body": body},
                                    ensure_ascii=False) + "\n")
        return {**record, "ok": True, "delivered": "outbox",
                "note": f"No SES configured, written to {outbox}"}

    import boto3
    boto3.client("ses").send_email(
        Source=os.getenv("SES_FROM"),
        Destination={"ToAddresses": [to]},
        Message={"Subject": {"Data": subject},
                 "Body": {"Text": {"Data": body}}})
    return {**record, "ok": True, "delivered": "ses"}
