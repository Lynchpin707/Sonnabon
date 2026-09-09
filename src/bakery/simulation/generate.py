"""A bakery's year, simulated down to the minute.

Written for one reason: to make sell-outs happen on purpose, and to know when
they did. A real till export tells you forty croissants were sold. It cannot
tell you whether sixty people wanted one, and no amount of cleverness recovers
that from the file. Here we generate the demand first, then serve it out of a
limited tray, so the truth is known and the detector can be scored against it.

Everything is seeded. Two runs with the same seed produce the same year, or the
numbers in a demo change every time somebody re-runs it and nobody can tell a
fix from a coincidence.

The shop trades 07:00 to 19:30 and closes Mondays, which is ordinary for a
French pâtisserie and gives the week a shape a flat simulator would miss.
"""

import json
import math
import random
from datetime import date, datetime, time, timedelta

from ..core import catalogue


from ..core.receipts import Bill, Line, save

OPEN, CLOSE = time(7, 0), time(19, 30)
CLOSED_WEEKDAY = 0  # Monday

# Saturday carries the week; Tuesday is the graveyard shift. These multiply the
# base rate, so they change volume without changing the shape of the day.
DAY_OF_WEEK = {1: 0.82, 2: 0.88, 3: 0.95, 4: 1.15, 5: 1.55, 6: 1.30}

# When each kind of thing actually sells. Weights are per opening half-hour and
# get normalised, so they express shape only. Bread goes twice, morning and the
# walk home; pâtisserie is an afternoon habit; viennoiserie is over by eleven.
SHAPES = {
    "bread":        [3, 6, 8, 6, 4, 3, 3, 4, 4, 3, 3, 4, 6, 8, 7, 5, 3, 2, 1, 1, 1, 1, 1, 1, 1],
    "viennoiserie": [5, 9, 10, 8, 5, 3, 2, 2, 2, 2, 2, 2, 2, 2, 2, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1],
    "patisserie":   [1, 1, 2, 2, 3, 4, 5, 6, 6, 5, 4, 4, 5, 6, 7, 7, 6, 5, 4, 3, 2, 2, 1, 1, 1],
    "biscuit":      [2, 3, 3, 3, 3, 3, 3, 3, 3, 3, 3, 3, 3, 3, 3, 3, 3, 3, 3, 2, 2, 2, 2, 2, 2],
    "drink":        [6, 9, 9, 7, 5, 4, 3, 3, 3, 4, 4, 3, 3, 3, 3, 2, 2, 2, 2, 1, 1, 1, 1, 1, 1],
}

# Typical units a day at an ordinary midweek rate, before any multiplier.
BASE_DEMAND = {
    "Croissant": 152, "Glazed donut": 78,
    "Cinnamon roll": 104, "Pistachio croissant": 62,
    "Tiramisu": 34, "Basque cheesecake": 48,
    "Chocolate éclair": 29,
    "Chocolate chip cookie": 92,
    "Coffee": 215,
}

# Products do not sit still for a year. One thing catches on, another quietly
# dies, and the owner is the last to notice because each week looks like the
# last. Expressed as the multiplier reached by the end of the period, applied
# smoothly across it. Anything not listed stays flat, which is most of the board.
DRIFT = {
    "Tiramisu": 1.85,   # the new signature, spreading by word of mouth
    "Pistachio croissant": 1.30,
    "Chocolate éclair": 0.62,          # quietly going out of fashion
    "Glazed donut": 0.80,
}


def _drift(day, item, start, end):
    """Where this product is on its way from start to finish."""
    target = DRIFT.get(item)
    if not target:
        return 1.0
    span = max((end - start).days, 1)
    through = (day - start).days / span
    return 1.0 + (target - 1.0) * through


# Occasions that move volume, as (month, day, days_before, peak_multiplier) and
# the products that carry them. The ramp is linear into the date, which is crude
# but it is the shape an owner would recognise: it builds for a week, not a day.
OCCASIONS = [
    ("Halloween", 10, 31, 6, 1.8,
     ["Cinnamon roll", "Glazed donut", "Chocolate chip cookie"]),
    ("Christmas", 12, 25, 14, 3.2,
     ["Basque cheesecake", "Tiramisu",
      "Chocolate éclair"]),
    ("Valentine", 2, 14, 4, 1.9,
     ["Chocolate éclair", "Tiramisu"]),
    ("Eid", 3, 20, 6, 2.3,
     ["Cinnamon roll", "Chocolate chip cookie", "Pistachio croissant"]),
    ("Easter", 4, 12, 7, 1.9,
     ["Chocolate éclair", "Basque cheesecake"]),
    ("Mother's Day", 5, 11, 5, 2.1,
     ["Basque cheesecake", "Tiramisu"])]

def _occasion_multiplier(day, item):
    """How much a date lifts one product. Multiplicative and capped at the peak,
    so overlapping occasions do not compound into nonsense."""
    best = 1.0
    for _, month, dom, lead, peak, items in OCCASIONS:
        if item not in items:
            continue
        target = date(day.year, month, dom)
        gap = (target - day).days
        if 0 <= gap <= lead:
            # Linear ramp: full peak on the day, 1.0 at the start of the lead.
            best = max(best, 1.0 + (peak - 1.0) * (1 - gap / lead))
    return best


def _trading_days(start, end):
    day = start
    while day <= end:
        if day.weekday() != CLOSED_WEEKDAY:
            yield day
        day += timedelta(days=1)


def _slots():
    """Half-hour slots from open to close, as (start_datetime_time, weight_index)."""
    out, cursor = [], datetime.combine(date(2000, 1, 1), OPEN)
    closing = datetime.combine(date(2000, 1, 1), CLOSE)
    index = 0
    while cursor < closing:
        out.append((cursor.time(), index))
        cursor += timedelta(minutes=30)
        index += 1
    return out


SLOTS = _slots()


def _arrival_times(rng, day, product, count):
    """Scatter ``count`` wanted-purchases across the day in the right shape.

    These are attempts, not sales. Whether each one becomes a sale depends on
    whether there is any left by then, which is decided in ``simulate``.
    """
    weights = SHAPES[product.category][:len(SLOTS)]
    total = sum(weights)
    times = []
    for _ in range(count):
        roll, running = rng.random() * total, 0.0
        for (start, index), weight in zip(SLOTS, weights):
            running += weight
            if roll <= running:
                minute = rng.randrange(30)
                times.append(datetime.combine(day, start) + timedelta(minutes=minute))
                break
    return sorted(times)


def _naive_bake(rng, product, day, history):
    """What the owner bakes today, doing it the way owners actually do it.

    Last week's same weekday, nudged by feel, rounded to a tray. Crucially it is
    blind to the occasion calendar, which is precisely the failure the agent
    exists to fix: the shop under-bakes into every holiday it did not think
    about, sells out at eleven, and never learns because the till only records
    what left the shelf.
    """
    same_weekday = [units for past, units in history.get(product.name, [])
                    if past.weekday() == day.weekday()]
    if same_weekday:
        guess = sum(same_weekday[-3:]) / len(same_weekday[-3:])
    else:
        guess = BASE_DEMAND[product.name] * DAY_OF_WEEK[day.weekday()]

    # The buffer every baker carries in their head. Without it the rule feeds on
    # its own censored history and spirals to nothing, which is the real failure
    # mode but far faster here than in a shop where a person eventually notices.
    # With it you get what a real bakery actually has: waste most days, and a
    # sell-out whenever something the calendar knew about arrives unannounced.
    guess *= 1.08 * rng.uniform(0.93, 1.07)
    tray = 12 if product.category != "bread" else 20
    return max(tray, math.ceil(guess / tray) * tray)


def simulate(start, end, seed=7):
    """Trade the shop for a period.

    Returns (bills, truth). ``truth`` is what a till could never tell you: how
    many each day genuinely wanted, how many were made, and the moment the tray
    ran out. It exists so the sell-out detector can be scored rather than
    believed, and it is never handed to the agent.
    """
    rng = random.Random(seed)
    products = catalogue.PRODUCTS
    bills, truth, history, number = [], [], {}, 0

    for day in _trading_days(start, end):
        sales, day_truth = [], {}

        for product in products:
            rate = (BASE_DEMAND[product.name]
                    * DAY_OF_WEEK[day.weekday()]
                    * _occasion_multiplier(day, product.name)
                    * _drift(day, product.name, start, end)
                    * rng.uniform(0.80, 1.20))
            wanted = max(0, int(rng.gauss(rate, math.sqrt(max(rate, 1)) * 1.4)))
            wants = _arrival_times(rng, day, product, wanted)

            if product.bake_minutes == 0:
                made, served = wanted, wants          # coffee never runs out
            else:
                made = _naive_bake(rng, product, day, history)
                served = wants[:made]

            sold_out_at = served[-1] if (wanted > made and served) else None
            day_truth[product.name] = {
                "wanted": wanted, "made": made, "sold": len(served),
                "sold_out_at": sold_out_at.isoformat(timespec="minutes")
                if sold_out_at else None,
            }
            history.setdefault(product.name, []).append((day, len(served)))
            sales.extend((moment, product) for moment in served)

        # Key on the moment only. Two sales in the same minute must not fall
        # through to comparing Product, which has no order and would raise.
        sales.sort(key=lambda pair: pair[0])
        # Bundle nearby sales into one bill. Somebody buying a croissant and a
        # coffee at 08:12 is one customer, and basket analysis needs that to be
        # one receipt rather than two.
        cursor = 0
        while cursor < len(sales):
            moment, product = sales[cursor]
            basket = {product.name: 1}
            cursor += 1
            while (cursor < len(sales)
                   and (sales[cursor][0] - moment).total_seconds() <= 120
                   and sum(basket.values()) < 5
                   and rng.random() < 0.55):
                basket[sales[cursor][1].name] = basket.get(sales[cursor][1].name, 0) + 1
                cursor += 1
            number += 1
            bills.append(Bill(
                number=number, at=moment,
                lines=tuple(Line(name, qty, catalogue.get(name).price)
                            for name, qty in basket.items()),
                payment="card" if rng.random() < 0.72 else "cash"))

        truth.append({"day": day.isoformat(), "products": day_truth})

    return bills, truth


def write(start, end, bills_path="data/bills.jsonl", truth_path="data/truth.json",
          seed=7):
    import os
    os.makedirs(os.path.dirname(bills_path) or ".", exist_ok=True)
    bills, truth = simulate(start, end, seed=seed)
    save(bills, bills_path)
    with open(truth_path, "w", encoding="utf-8") as handle:
        json.dump(truth, handle, ensure_ascii=False, indent=1)
    return bills, truth
