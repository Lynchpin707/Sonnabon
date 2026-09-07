"""Occasions, and how far ahead each one has to be started.

An occasion is not a date. It is a backward schedule hanging off a date, and the
lead time is the part nobody keeps in their head. Ordering more butter three
weeks out is a different task from baking more on the day, and the shop that
only remembers the second one sells out at eleven and cannot make more.

Dates that move each year are flagged and set per year rather than computed. A
wrong Easter is worse than no Easter, and a lunar calendar is not something to
approximate in a module about pastry.
"""

from dataclasses import dataclass, field
from datetime import date, timedelta


@dataclass(frozen=True)
class Task:
    """One step in the run-up, measured in days before the occasion."""

    days_before: int
    what: str
    owner: str = "owner"

    def due(self, on):
        return on - timedelta(days=self.days_before)


@dataclass(frozen=True)
class Occasion:
    name: str
    month: int
    day: int
    lead_days: int
    peak_multiplier: float
    products: tuple
    tasks: tuple = ()
    moves_yearly: bool = False

    def date_in(self, year):
        return date(year, self.month, self.day)

    def next_after(self, today):
        """The next time this comes round. Occasions do not stop at new year."""
        this_year = self.date_in(today.year)
        if this_year >= today:
            return this_year
        return self.date_in(today.year + 1)


# The standard run-up. Most occasions share it, and the ones that do not say so.
STANDARD_TASKS = (
    Task(28, "Decide what goes on the board for this occasion"),
    Task(21, "Raise the ingredient order, suppliers need notice for a quantity change"),
    Task(14, "Trial batch, so there is time to change it before it matters", "baker"),
    Task(10, "Price it and put it on the board"),
    Task(7, "Confirm extra hands for the peak days"),
    Task(2, "Final quantities to the team", "baker"))

OCCASIONS = [
    Occasion("Halloween", 10, 31, 6, 1.8,
             ("Cinnamon roll", "Glazed donut",
              "Chocolate chip cookie"), STANDARD_TASKS),
    Occasion("Christmas", 12, 25, 14, 3.2,
             ("Basque cheesecake", "Tiramisu",
              "Chocolate éclair"),
             STANDARD_TASKS + (Task(35, "Open pre-orders, the peak days cannot "
                                        "absorb walk-ins"),)),
    Occasion("Valentine", 2, 14, 4, 1.9,
             ("Chocolate éclair", "Tiramisu"),
             STANDARD_TASKS),
    Occasion("Eid", 3, 20, 6, 2.3,
             ("Cinnamon roll", "Chocolate chip cookie",
              "Pistachio croissant"), STANDARD_TASKS, moves_yearly=True),
    Occasion("Easter", 4, 12, 7, 1.9,
             ("Chocolate éclair", "Basque cheesecake"),
             STANDARD_TASKS, moves_yearly=True),
    Occasion("Mother's Day", 5, 11, 5, 2.1,
             ("Basque cheesecake", "Tiramisu"),
             STANDARD_TASKS, moves_yearly=True),
]

for _occasion in OCCASIONS:
    if isinstance(_occasion.products, str):
        raise TypeError(
            f"{_occasion.name} lists its products as a string, not a tuple. A "
            f"single product needs a trailing comma: (\"{_occasion.products}\",). "
            f"Without it every letter is treated as a product.")

BY_NAME = {occasion.name: occasion for occasion in OCCASIONS}


def upcoming(today, within_days=60):
    """What is coming, soonest first, with how long is left.

    ``within_days`` is deliberately generous. The point of this module is to
    surface Christmas in October, and a two week horizon would surface it in
    December when the useful decisions have already been missed.
    """
    rows = []
    for occasion in OCCASIONS:
        when = occasion.next_after(today)
        away = (when - today).days
        if away <= within_days:
            rows.append({"occasion": occasion.name, "date": when,
                         "days_away": away, "products": list(occasion.products),
                         "peak_multiplier": occasion.peak_multiplier,
                         "moves_yearly": occasion.moves_yearly})
    return sorted(rows, key=lambda row: row["days_away"])


def schedule(occasion_name, today, year=None):
    """The backward schedule for one occasion, with what is already late.

    Overdue tasks are the whole value of this function. A plan that only lists
    what is coming lets a missed order stay invisible until the week itself.
    """
    occasion = BY_NAME[occasion_name]
    when = occasion.date_in(year) if year else occasion.next_after(today)
    rows = []
    for task in occasion.tasks:
        due = task.due(when)
        rows.append({"due": due, "days_from_now": (due - today).days,
                     "what": task.what, "owner": task.owner,
                     "overdue": due < today})
    return {"occasion": occasion.name, "date": when,
            "days_away": (when - today).days,
            "products": list(occasion.products),
            "tasks": sorted(rows, key=lambda row: row["due"])}


def multiplier(day, item):
    """How much this date lifts this product, ramping in over the lead time.

    Capped at the peak rather than compounded, so two occasions falling close
    together do not multiply into a quantity nobody could bake.
    """
    best = 1.0
    for occasion in OCCASIONS:
        if item not in occasion.products:
            continue
        target = occasion.date_in(day.year)
        gap = (target - day).days
        if 0 <= gap <= occasion.lead_days:
            ramp = 1.0 + (occasion.peak_multiplier - 1.0) * (1 - gap / occasion.lead_days)
            best = max(best, ramp)
    return best


def whats_due(today, within_days=45):
    """Every task from every upcoming occasion, in date order.

    This is what the weekly run reads. Occasions are handled as one queue rather
    than one at a time, because occasions overlap and the ingredient orders for two
    of them can land in the same week.
    """
    rows = []
    for row in upcoming(today, within_days + 40):
        for task in schedule(row["occasion"], today)["tasks"]:
            if task["overdue"] or task["days_from_now"] <= within_days:
                rows.append({**task, "occasion": row["occasion"]})
    return sorted(rows, key=lambda row: row["due"])


# ── what the shop actually did last time ────────────────────────────────────
#
# Every multiplier above is a prior: a number somebody typed, useful for
# generating trade and for a shop with no history yet. It is not a fact about
# this shop, and saying "normally lifts by 1.8x" about a figure nobody measured
# is the exact failure this project exists to avoid.
#
# So when the receipts cover a past occurrence, measure it instead.

MIN_BASELINE_DAYS = 6            # below this the ratio is noise wearing a number


def peak_window(occasion, when):
    """The days the occasion is actually lifting, ramp included."""
    return [when - timedelta(days=gap) for gap in range(occasion.lead_days + 1)]


def observed_lift(units_by_day, occasion_name, products=None):
    """Measure the lift from the till, weekday by weekday.

    Weekday matching is not fussiness. A seven day window against an all-days
    average compares a Saturday to a Tuesday and reports the weekend as
    Halloween. Each occasion day is scored against the same weekday in the
    ordinary weeks around it, and days belonging to any other occasion are
    excluded so two dates close together cannot borrow each other's peak.

    Returns None when there is no past occurrence, which is a real answer: a
    shop three months old has never seen Christmas, and inventing a number for
    it is worse than saying so.
    """
    occasion = BY_NAME[occasion_name]
    days = sorted(units_by_day)
    if not days:
        return None

    # Every day that any occasion is touching, so the baseline stays ordinary.
    lifted = set()
    for other in OCCASIONS:
        for year in range(days[0].year, days[-1].year + 1):
            try:
                lifted.update(peak_window(other, other.date_in(year)))
            except ValueError:                       # 29 February in a flat year
                continue

    per_product = {}
    for item in (products or occasion.products):
        ratios, peak_days, base_days = [], 0, 0
        for year in range(days[0].year, days[-1].year + 1):
            try:
                when = occasion.date_in(year)
            except ValueError:
                continue
            window = [day for day in peak_window(occasion, when)
                      if day in units_by_day]
            if not window:
                continue

            # Ordinary trade either side, same season, same weekdays.
            near = [day for day in days
                    if 0 < abs((day - when).days) <= 56 and day not in lifted]
            baseline = {}
            for day in near:
                baseline.setdefault(day.weekday(), []).append(
                    units_by_day[day].get(item, 0))
            if sum(len(v) for v in baseline.values()) < MIN_BASELINE_DAYS:
                continue

            for day in window:
                same = baseline.get(day.weekday())
                if not same or sum(same) == 0:
                    continue
                ordinary = sum(same) / len(same)
                ratios.append(units_by_day[day].get(item, 0) / ordinary)
                peak_days += 1
            base_days += sum(len(v) for v in baseline.values())

        if not ratios:
            continue
        per_product[item] = {"lift": round(max(ratios), 2),
                             "mean_lift": round(sum(ratios) / len(ratios), 2),
                             "days": peak_days, "baseline_days": base_days}

    if not per_product:
        return None

    peaks = [row["lift"] for row in per_product.values()]
    return {
        "occasion": occasion.name,
        "measured": True,
        "peak_multiplier": round(sum(peaks) / len(peaks), 2),
        "assumed": occasion.peak_multiplier,
        "products": per_product,
        "days_seen": sum(row["days"] for row in per_product.values()),
    }
