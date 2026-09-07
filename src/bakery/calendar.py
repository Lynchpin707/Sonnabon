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
    Task(2, "Final quantities to the team", "baker"),
)

OCCASIONS = [
    Occasion("Halloween", 10, 31, 6, 1.8,
             ("Cinnamon roll", "Glazed donut", "Brownie",
              "Chocolate chip cookie"), STANDARD_TASKS),
    Occasion("Christmas", 12, 25, 14, 3.2,
             ("Basque cheesecake", "Crème brûlée crêpe cake", "Lemon tart",
              "Carrot cake slice", "Chocolate éclair"),
             STANDARD_TASKS + (Task(35, "Open pre-orders, the peak days cannot "
                                        "absorb walk-ins"),)),
    Occasion("Valentine", 2, 14, 4, 1.9,
             ("Chocolate éclair", "Brownie", "Crème brûlée crêpe cake"),
             STANDARD_TASKS),
    Occasion("Eid", 3, 20, 6, 2.3,
             ("Cinnamon roll", "Brownie", "Chocolate chip cookie",
              "Pistachio croissant"), STANDARD_TASKS, moves_yearly=True),
    Occasion("Easter", 4, 12, 7, 1.9,
             ("Carrot cake slice", "Chocolate éclair", "Lemon tart"),
             STANDARD_TASKS, moves_yearly=True),
    Occasion("Mother's Day", 5, 11, 5, 2.1,
             ("Basque cheesecake", "Lemon tart", "Matcha roll cake"),
             STANDARD_TASKS, moves_yearly=True),
]

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
