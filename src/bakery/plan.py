"""Tomorrow's bake, decided rather than remembered.

Three steps, in this order, because reversing any two of them gives a confident
wrong answer:

    1. Correct the history. Days the product sold out are not observations of
       demand, they are observations of the tray. Using them raw is how a shop
       bakes less every year.
    2. Forecast from the corrected history, on the matching weekday, lifted by
       whatever the calendar says is coming.
    3. Pick the quantity from the forecast and the product's own economics.
       Cheap staples get made past the point of certainty because running out
       costs more than binning. Expensive pastry does not.

Step three is the one nobody in a small bakery does, and it is a single line of
arithmetic once the first two are honest.
"""

import math
import statistics
from collections import defaultdict
from datetime import timedelta

from . import calendar, catalogue
from .analytics import Index, estimate_true_demand, find_sellouts

NORMAL = statistics.NormalDist()

# How many matching weekdays to look back over. Six weeks is long enough for the
# mean to settle and short enough that a menu change from the spring does not
# still be steering the plan in autumn.
LOOKBACK_WEEKS = 6

# Nothing is baked in ones. Rounding up to a tray is not a detail, it is how the
# oven actually works, and a plan that says 37 croissants gets ignored.
TRAY = {"bread": 20, "viennoiserie": 12, "patisserie": 6, "biscuit": 12}


def corrected_history(bills, index=None):
    """{item: {day: units}} with sold-out days replaced by estimates.

    This is the only history anything downstream should ever see. Returned
    alongside the set of days that were corrected, so a caller can show its
    working rather than quietly presenting an estimate as a measurement.
    """
    index = index or Index(bills)
    history = defaultdict(dict)
    for day, row in index.units.items():
        for item, units in row.items():
            history[item][day] = float(units)

    corrected = defaultdict(set)
    sellouts = find_sellouts(bills, index=index)
    by_item = defaultdict(set)
    for row in sellouts:
        by_item[row["item"]].add(row["day"])

    for item, days in by_item.items():
        curve, _ = index.curve(item, frozenset(days))
        if curve is None:
            continue
        for day in days:
            estimate = estimate_true_demand(bills, day, item, curve=curve,
                                            index=index)
            if estimate["confidence"] in ("good", "fair"):
                history[item][day] = float(estimate["estimate"])
                corrected[item].add(day)

    return dict(history), dict(corrected)


def forecast(history, item, target_day, occasion_multiplier=None):
    """Mean and spread for one product on one future day.

    Matching weekday only. A Saturday forecast built from Tuesdays is the single
    most common way a bakery under-bakes its best day, and averaging the week
    together hides it completely.
    """
    series = history.get(item, {})
    matching = sorted((day, units) for day, units in series.items()
                      if day.weekday() == target_day.weekday()
                      and day < target_day)
    recent = [units for _, units in matching[-LOOKBACK_WEEKS:]]

    if not recent:
        # Fall back to every day rather than refusing. A new product with no
        # matching weekday still has to be baked tomorrow.
        recent = [units for _, units in sorted(series.items())[-LOOKBACK_WEEKS:]]
    if not recent:
        return None

    mean = statistics.fmean(recent)
    # Poisson-ish floor on the spread. Two identical weeks would otherwise give
    # zero variance and a plan with no safety margin at all.
    spread = statistics.stdev(recent) if len(recent) > 1 else 0.0
    spread = max(spread, mean ** 0.5)

    lift = (occasion_multiplier or calendar.multiplier)(target_day, item)
    return {"item": item, "day": target_day,
            "mean": round(mean * lift, 1),
            "sd": round(spread * lift, 1),
            "weeks_used": len(recent),
            "occasion_lift": round(lift, 2)}


def quantity(product, mean, sd):
    """How many to make, given what it costs to be wrong in each direction."""
    ratio = product.critical_ratio
    if ratio <= 0:
        return 0
    target = mean + NORMAL.inv_cdf(min(max(ratio, 0.001), 0.999)) * sd
    tray = TRAY.get(product.category, 6)
    if target <= 0:
        return 0
    return max(tray, math.ceil(target / tray) * tray)


def bake_plan(bills, target_day, index=None, history=None, oven_minutes=None):
    """The list that goes to the team.

    ``oven_minutes`` trims the plan when the optimum does not fit. Trimming
    removes from the lowest margin per oven minute upward, which is the correct
    order and the one an exhausted person at 20:40 gets wrong.
    """
    index = index or Index(bills)
    if history is None:
        history, corrected = corrected_history(bills, index=index)
    else:
        corrected = {}

    rows = []
    for product in catalogue.baked():
        estimate = forecast(history, product.name, target_day)
        if estimate is None:
            continue
        units = quantity(product, estimate["mean"], estimate["sd"])
        rows.append({
            "item": product.name,
            "make": units,
            "forecast": estimate["mean"],
            "sd": estimate["sd"],
            "service_level": round(product.critical_ratio, 2),
            "occasion_lift": estimate["occasion_lift"],
            "oven_minutes": round(units * product.bake_minutes, 1),
            "margin_per_oven_minute": product.margin_per_oven_minute,
            "corrected_days": len(corrected.get(product.name, ())),
        })

    rows.sort(key=lambda row: -(row["margin_per_oven_minute"] or 0))
    total = sum(row["oven_minutes"] for row in rows)
    trimmed = []

    if oven_minutes and total > oven_minutes:
        # Cut from the bottom of the margin-per-minute ranking, but never below
        # the forecast itself. Everything above the forecast is safety stock and
        # is fair game; everything below it is demand we already expect, and
        # trimming into that manufactures the exact sell-out this whole module
        # exists to prevent. If the oven still does not fit after that, the shop
        # has a capacity problem and a plan cannot solve it quietly.
        over = total - oven_minutes
        for row in reversed(rows):
            if over <= 0:
                break
            product = catalogue.get(row["item"])
            tray = TRAY.get(product.category, 6)
            floor = math.ceil(row["forecast"] / tray) * tray
            while over > 0 and row["make"] - tray >= floor:
                row["make"] -= tray
                over -= tray * product.bake_minutes
                row["oven_minutes"] = round(row["make"] * product.bake_minutes, 1)
                trimmed.append({"item": row["item"], "cut": tray})
        total = sum(row["oven_minutes"] for row in rows)
        if over > 0:
            # Say so rather than cutting into demand. An honest "this does not
            # fit" is a decision for the owner; a silently short plan is not.
            trimmed.append({"item": "OVER CAPACITY",
                            "cut": round(over),
                            "note": "cannot fit without baking under forecast"})

    return {
        "day": target_day,
        "rows": sorted(rows, key=lambda row: row["item"]),
        "oven_minutes": round(total, 1),
        "oven_capacity": oven_minutes,
        "trimmed": trimmed,
        "units": sum(row["make"] for row in rows),
    }


def tomorrow(bills, today, **kwargs):
    return bake_plan(bills, today + timedelta(days=1), **kwargs)
