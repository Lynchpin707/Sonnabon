"""What can be worked out from a pile of till receipts, and what cannot.

The hard problem here is that a till records what left the shelf, never what
somebody wanted and did not find. A day where everything sold out looks, in the
data, like a very good day. Left uncorrected, a forecaster trained on this
learns to bake less every year and never finds out why.

The correction is ordinary statistics rather than anything clever. Learn how a
product normally sells through the day, using only days it did not run out.
Then on a day it did run out, look at how far through that curve it had got when
the last one went, and scale up. Sell out at noon having done half a normal
day's trade and roughly twice as many people wanted one as got one.

The estimate is an estimate. Every function here returns its confidence and the
evidence behind it, because a censoring correction stated as a fact is exactly
the kind of confident wrong number this module exists to prevent.
"""

from collections import defaultdict
from datetime import datetime, time, timedelta

from . import catalogue
from .receipts import units_by_day

OPEN, CLOSE = time(7, 0), time(19, 30)

# Below this share of a normal day, the scale-up is dividing by a small number
# and the answer is arithmetic rather than evidence. Sold out at 08:00 having
# done 6% of a day, a naive estimate says demand was sixteen times supply. It
# might have been. We say so, and we say we do not know.
MIN_CURVE_FRACTION = 0.25

# A product needs this many clean days before its shape means anything.
MIN_CLEAN_DAYS = 8


def _minutes_open(moment):
    """Minutes from opening to ``moment``, clamped to trading hours."""
    start = datetime.combine(moment.date(), OPEN)
    end = datetime.combine(moment.date(), CLOSE)
    return max(0.0, min((moment - start).total_seconds() / 60,
                        (end - start).total_seconds() / 60))


TRADING_MINUTES = _minutes_open(datetime.combine(datetime.today().date(), CLOSE))


def last_sale_times(bills):
    """{date: {item: last time it sold}}. The raw signal for everything here."""
    latest = defaultdict(dict)
    for bill in bills:
        for line in bill.lines:
            day = latest[bill.day]
            if line.item not in day or bill.at > day[line.item]:
                day[line.item] = bill.at
    return dict(latest)


def sale_curve(bills, item, exclude_days=()):
    """How ``item`` normally sells through the day.

    Returns a list of 26 cumulative fractions, one per half hour, so that
    ``curve[k]`` is the share of a day's sales normally done by the end of slot
    k. Built only from days the product traded to the end, because a day it ran
    out has a curve that stops early by definition and would drag the shape
    forward if included.
    """
    slots = int(TRADING_MINUTES // 30) + 1
    totals = [0.0] * slots
    days_used = 0
    per_day = defaultdict(lambda: [0.0] * slots)

    for bill in bills:
        if bill.day in exclude_days:
            continue
        qty = bill.qty_of(item)
        if qty:
            slot = min(int(_minutes_open(bill.at) // 30), slots - 1)
            per_day[bill.day][slot] += qty

    for counts in per_day.values():
        day_total = sum(counts)
        if day_total <= 0:
            continue
        running = 0.0
        for index, value in enumerate(counts):
            running += value
            totals[index] += running / day_total
        days_used += 1

    if days_used < MIN_CLEAN_DAYS:
        return None, days_used
    return [value / days_used for value in totals], days_used


# How many sales the shape has to say were still due before silence counts as
# evidence. Below this the silence proves nothing: sales taper toward closing,
# so the last gap of the day is long for everything and a threshold based on the
# daily average flags half the menu every evening.
MIN_EXPECTED_REMAINING = 3.0


def find_sellouts(bills, on=None, index=None):
    """Products whose tray emptied while the shape said more were still due.

    The test is not how long the silence was. It is how many sales the product
    normally still had ahead of it at that hour. Sell out at noon with two
    thirds of the day's trade still to come and the silence is decisive. Go
    quiet at six when only half a sale was due anyway and it means nothing.

    Two passes, because the curve wants to exclude sell-out days and finding
    sell-out days wants the curve. The first pass uses every day and is slightly
    biased early; the second rebuilds the shape without whatever it found. One
    round of that is enough to settle.
    """
    index = index or Index(bills)
    days = [on] if on else sorted(index.last)

    daily = defaultdict(list)
    for row in index.units.values():
        for item, units in row.items():
            daily[item].append(units)
    typical = {item: sum(values) / len(values) for item, values in daily.items()}

    def sweep(excluded):
        hits = []
        for day in days:
            items = index.last.get(day, {})
            if not items:
                continue
            shop_last = max(items.values())
            for item, moment in items.items():
                product = catalogue.get(item)
                if product.bake_minutes <= 0 or typical.get(item, 0) <= 0:
                    continue
                curve, _ = index.curve(item, excluded.get(item, frozenset()))
                if curve is None:
                    continue
                slot = min(int(_minutes_open(moment) // 30), len(curve) - 1)
                still_due = typical[item] * (1 - curve[slot])
                # The shop has to have kept trading, or an early close looks
                # exactly like every product selling out at once.
                if (still_due >= MIN_EXPECTED_REMAINING
                        and (shop_last - moment).total_seconds() / 60 >= 30):
                    hits.append({"day": day, "item": item, "last_sale": moment,
                                 "expected_remaining": round(still_due, 1),
                                 "day_fraction_done": round(curve[slot], 3)})
        return hits

    first = sweep({})
    excluded = defaultdict(set)
    for row in first:
        excluded[row["item"]].add(row["day"])
    return sweep({item: frozenset(value) for item, value in excluded.items()})


class Index:
    """Everything scanned once, so nothing scans the pile again.

    Without this, estimating a year of sell-outs walks 158,000 bills a thousand
    times over. Building the tables up front turns that from minutes into
    milliseconds, and it is the difference between an agent that can run this
    inside a request and one that times out.
    """

    def __init__(self, bills):
        self.bills = bills
        self.units = units_by_day(bills)
        self.last = last_sale_times(bills)
        self._curves = {}

    def curve(self, item, exclude_days):
        key = (item, frozenset(exclude_days))
        if key not in self._curves:
            self._curves[key] = sale_curve(self.bills, item,
                                           exclude_days=exclude_days)
        return self._curves[key]


def estimate_true_demand(bills, day, item, curve=None, index=None):
    """What demand probably was, on a day the product ran out.

    Returns a dict carrying the estimate, the range around it, the evidence and
    an explicit confidence. Never returns a bare number: the caller has to see
    how much of the day the shape was extrapolating over before quoting it.
    """
    index = index or Index(bills)
    sold = index.units.get(day, {}).get(item, 0)
    latest = index.last.get(day, {}).get(item)
    if not latest or sold == 0:
        return {"item": item, "day": day, "sold": sold, "estimate": sold,
                "confidence": "none", "why": "no sales recorded"}

    if curve is None:
        sellout_days = {row["day"] for row in find_sellouts(bills)
                        if row["item"] == item}
        curve, clean_days = index.curve(item, sellout_days)
        if curve is None:
            return {"item": item, "day": day, "sold": sold, "estimate": sold,
                    "confidence": "none",
                    "why": f"only {clean_days} clean days, need {MIN_CLEAN_DAYS}"}

    slot = min(int(_minutes_open(latest) // 30), len(curve) - 1)
    fraction = curve[slot]

    if fraction <= 0:
        return {"item": item, "day": day, "sold": sold, "estimate": sold,
                "confidence": "none", "why": "no normal sales this early"}

    estimate = sold / fraction
    # The uncertainty is dominated by how much of the day we are extrapolating
    # over, so express it that way rather than inventing a standard error.
    spread = (1 - fraction) * 0.35
    low, high = estimate * (1 - spread), estimate * (1 + spread)

    if fraction >= 0.6:
        confidence = "good"
    elif fraction >= MIN_CURVE_FRACTION:
        confidence = "fair"
    else:
        confidence = "poor"

    return {
        "item": item, "day": day, "sold": sold,
        "sold_out_at": latest.strftime("%H:%M"),
        "day_fraction_done": round(fraction, 3),
        "estimate": round(estimate),
        "range": (round(low), round(high)),
        "missed": max(0, round(estimate) - sold),
        "lost_margin": round(max(0, estimate - sold) * catalogue.get(item).margin, 2),
        "confidence": confidence,
        "why": (f"sold {sold} by {latest:%H:%M}, which is normally "
                f"{fraction:.0%} of a day for this product"),
    }


def lost_to_sellouts(bills, days=None):
    """Every sell-out in the period, priced.

    This is the number an owner has never seen, because nothing they own could
    have produced it. Poor-confidence rows are returned but flagged, and the
    total is given both ways so nobody quotes the optimistic one by accident.
    """
    index = Index(bills)
    rows = []
    sellouts = find_sellouts(bills)
    if days is not None:
        sellouts = [row for row in sellouts if row["day"] in set(days)]

    by_item = defaultdict(list)
    for row in sellouts:
        by_item[row["item"]].append(row["day"])

    for item, item_days in by_item.items():
        # One curve per product, learned without its own sell-out days, then
        # reused for every one of them. Rebuilding it per day would be both slow
        # and subtly wrong, since the exclusion set would keep changing.
        curve, _ = index.curve(item, set(item_days))
        for day in item_days:
            if curve is None:
                continue
            rows.append(estimate_true_demand(bills, day, item, curve=curve,
                                             index=index))

    trusted = [row for row in rows if row["confidence"] in ("good", "fair")]
    return {
        "sellouts": len(rows),
        "priced": len(trusted),
        "lost_margin": round(sum(row["lost_margin"] for row in trusted), 2),
        "lost_margin_including_poor":
            round(sum(row["lost_margin"] for row in rows), 2),
        "rows": sorted(rows, key=lambda row: -row["lost_margin"]),
    }


def best_sellers(bills, days=None, top=None):
    """Ranked three ways, because the first two are the ones owners use and
    both are wrong.

    Units finds whatever is cheapest. Revenue finds whatever is dearest.
    Contribution finds what actually pays the rent, and contribution per oven
    minute finds what deserves the oven, which is a different answer again and
    the one nobody computes.
    """
    table = units_by_day(bills)
    if days is not None:
        wanted = set(days)
        table = {day: row for day, row in table.items() if day in wanted}

    totals = defaultdict(int)
    for row in table.values():
        for item, units in row.items():
            totals[item] += units

    rows = []
    for item, units in totals.items():
        product = catalogue.get(item)
        rows.append({
            "item": item,
            "units": units,
            "revenue": round(units * product.price, 2),
            "contribution": round(units * product.margin, 2),
            "per_oven_minute": (round(units * product.margin
                                      / (units * product.bake_minutes), 3)
                                if product.bake_minutes else None),
        })

    def rank(key):
        ordered = sorted([row for row in rows if row[key] is not None],
                         key=lambda row: -row[key])
        return [row["item"] for row in ordered][:top] if top else \
               [row["item"] for row in ordered]

    return {
        "by_units": rank("units"),
        "by_revenue": rank("revenue"),
        "by_contribution": rank("contribution"),
        "by_oven_minute": rank("per_oven_minute"),
        "rows": sorted(rows, key=lambda row: -row["contribution"]),
    }


def customers(bills, days=None):
    """Bills are customers. Counting them is trivial and no owner tracks it."""
    per_day = defaultdict(int)
    basket = defaultdict(float)
    for bill in bills:
        if days is not None and bill.day not in set(days):
            continue
        per_day[bill.day] += 1
        basket[bill.day] += bill.total
    if not per_day:
        return {"days": 0}
    counts = list(per_day.values())
    return {
        "days": len(counts),
        "total": sum(counts),
        "per_day": round(sum(counts) / len(counts), 1),
        "busiest": max(per_day, key=per_day.get),
        "quietest": min(per_day, key=per_day.get),
        "average_basket": round(sum(basket.values()) / sum(counts), 2),
    }


def day_of_week_shape(bills, item=None):
    """Average units per weekday. Most shops bake Tuesday's quantity on
    Saturday, which this makes obvious in one line."""
    table = units_by_day(bills)
    buckets = defaultdict(list)
    for day, row in table.items():
        buckets[day.weekday()].append(sum(row.values()) if item is None
                                      else row.get(item, 0))
    names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    return {names[index]: round(sum(values) / len(values), 1)
            for index, values in sorted(buckets.items()) if values}
