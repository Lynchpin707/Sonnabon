"""Who does what, and by when.

A bake list is not a plan until it has names on it. This turns the night's
quantities and the calendar's lead times into each person's own list, which is
the difference between a spreadsheet the owner reads and work the team can pick
up without being asked.

Roles decide who gets what. The baker takes production, the front takes the
counter and the ordering, and anything with money or a supplier on the other end
stays with the owner, because those are the decisions an agent should not be
making on somebody's behalf.
"""

import json
import os
from dataclasses import dataclass, asdict
from datetime import timedelta

from . import calendar as occasions, catalogue, state

TEAM_FILE = os.getenv("TEAM_FILE", "team.json")


@dataclass(frozen=True)
class Person:
    name: str
    role: str          # baker, front, owner
    starts: str        # when their shift begins


# A small shop: two in the kitchen, one on the counter, and the owner. Replaced
# wholesale by team.json once a real shop is onboarded.
DEFAULT = [
    Person("Nadia", "owner", "06:30"),
    Person("Karim", "baker", "03:00"),
    Person("Inès", "baker", "05:00"),
    Person("Tom", "front", "06:45"),
]


def roster():
    if os.path.exists(TEAM_FILE):
        with open(TEAM_FILE, encoding="utf-8") as handle:
            return [Person(**row) for row in json.load(handle)]
    return list(DEFAULT)


def save(people, path=TEAM_FILE):
    with open(path, "w", encoding="utf-8") as handle:
        json.dump([asdict(p) for p in people], handle, ensure_ascii=False, indent=2)
    return path


def _split_bake(rows, bakers):
    """Share the night's work out by oven order, heaviest first.

    Whoever starts earliest takes the long-proving things, which is how a real
    kitchen already works: the person in at three does the laminated dough, and
    the five o'clock start picks up what can be finished fast.
    """
    if not bakers:
        return {}
    ordered = sorted(rows, key=lambda row: -row["make"])
    lists = {person.name: [] for person in bakers}
    early = sorted(bakers, key=lambda person: person.starts)
    for position, row in enumerate(ordered):
        who = early[position % len(early)]
        lists[who.name].append({"item": row["item"], "make": row["make"],
                                "lifted": row["occasion_lift"] > 1.05})
    return lists


def today(plan=None):
    """Every person's list for the coming shift."""
    from . import tools

    people = roster()
    plan = plan or tools.bake_plan()
    bakers = [p for p in people if p.role == "baker"]
    bake_lists = _split_bake(plan["rows"], bakers)

    day = state.today()
    due = occasions.whats_due(day, within_days=45)

    board = []
    for person in people:
        jobs = []
        if person.role == "baker":
            for row in bake_lists.get(person.name, []):
                jobs.append({"what": f"{row['make']} {row['item'].lower()}",
                             "kind": "bake",
                             "flag": "occasion" if row["lifted"] else None})
        for task in due:
            if task["owner"] == person.role or (task["owner"] == "owner"
                                                and person.role == "owner"):
                jobs.append({"what": task["what"], "kind": "prep",
                             "due": task["due"].isoformat(),
                             "flag": "late" if task["overdue"] else None,
                             "occasion": task["occasion"]})
        board.append({"name": person.name, "role": person.role,
                      "starts": person.starts, "jobs": jobs})

    return {"day": day.isoformat(), "plan_day": plan["day"], "board": board,
            "units": plan["units"]}
