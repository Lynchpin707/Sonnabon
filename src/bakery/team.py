"""The board: who does what, whether they have done it, and by when.

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
import tempfile
from dataclasses import dataclass, asdict
from datetime import datetime
from datetime import timedelta

from . import paths, calendar as occasions, catalogue, state

TEAM_FILE = paths.of("team")


@dataclass(frozen=True)
class Person:
    name: str
    role: str          # baker, front, owner
    starts: str        # when their shift begins


# A small shop: two in the kitchen, one on the counter, and the owner. Names are
# placeholders and deliberately from nowhere in particular, because the shop
# this runs for could be anywhere. Replaced wholesale by team.json on onboarding.
DEFAULT = [
    Person("Amara", "owner", "06:30"),
    Person("Luca", "baker", "03:00"),
    Person("Mei", "baker", "05:00"),
    Person("Sam", "front", "06:45"),
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
    # Today's work, not the planning calendar. Asking for the next forty-five
    # days put three run-up tasks on the owner, which is backwards for a thing
    # whose job is taking work off them, and matched every baker against every
    # baker task so the same trial batch appeared on two boards. What is coming
    # lives on the diary; what lands here is due today or already late.
    due = occasions.whats_due(day, within_days=0)

    shop = state.get()
    suspected = [row for row in shop.index.sellouts() if row["day"] == day]
    shop_last = lambda row: shop.index.last[day][row["item"]].strftime("%H:%M")

    board = []
    claimed = set()
    for person in people:
        jobs = []
        if person.role == "baker":
            for row in bake_lists.get(person.name, []):
                jobs.append({"what": f"{row['make']} {row['item'].lower()}",
                             "kind": "bake",
                             "flag": "occasion" if row["lifted"] else None})
        if person.role == "front":
            # The agent works out what ran out from the timestamps, which is an
            # inference. Somebody standing at the counter knows. Confirming it
            # turns a good guess into a fact the next forecast can lean on, and
            # it costs whoever closes up about a minute.
            jobs.append({
                "what": "Confirm what ran out today, and when",
                "kind": "check",
                "flag": None,
                "detail": [{"item": row["item"],
                            "at": shop_last(row)}
                           for row in suspected],
            })

        for task in due:
            if task["owner"] != person.role or task["what"] in claimed:
                continue
            # One task, one person. Matching on role alone handed the same job
            # to everyone who shared it.
            claimed.add(task["what"])
            jobs.append({"what": task["what"], "kind": "prep",
                         "due": task["due"].isoformat(),
                         "flag": "late" if task["overdue"] else None,
                         "occasion": task["occasion"]})
        board.append({"name": person.name, "role": person.role,
                      "starts": person.starts, "jobs": jobs})

    # A stable id per job, so a tick survives a refresh and means the same
    # thing to whoever opens the board next. Built from the day, the person and
    # the job itself rather than a position, because the list reorders.
    ticked = all_for(day)
    total = 0
    for person in board:
        for job in person["jobs"]:
            job["id"] = f"{day}|{person['name']}|{job['what']}"
            job["done"] = job["id"] in ticked
            total += 1
            for row in job.get("detail", ()):
                row["id"] = f"{job['id']}|{row['item']}"
                row["done"] = row["id"] in ticked
                total += 1

    # Counted from the jobs actually on the board, not from the size of the
    # ticket store. Anything in the store that no longer matches a job, from a
    # bad id or from yesterday's plan, would otherwise show as work done with
    # nothing ticked to show for it.
    real = {job["id"] for person in board for job in person["jobs"]}
    real |= {row["id"] for person in board for job in person["jobs"]
             for row in job.get("detail", ())}
    done = len(set(ticked) & real)
    return {"day": day.isoformat(), "plan_day": plan["day"], "board": board,
            "units": plan["units"],
            "progress": {"done": done, "total": total,
                         "share": round(done / total, 2) if total else 0.0}}


# ── which jobs are done ─────────────────────────────────────────────────
#
# Server side, not the browser. Two people share a kitchen and they are not
# on the same phone, so a checkbox that lives in one browser is decoration.

STORE = paths.of("tickets")


def _read():
    if not os.path.exists(STORE):
        return {}
    try:
        with open(STORE, encoding="utf-8") as handle:
            return json.load(handle)
    except (json.JSONDecodeError, OSError):
        # A half-written file must cost the ticks, never the shift.
        return {}


def _write(state):
    os.makedirs(os.path.dirname(STORE) or ".", exist_ok=True)
    # Write beside the target and move it into place, so a crash mid-write
    # leaves the old file rather than an empty one.
    handle = tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", delete=False,
        dir=os.path.dirname(STORE) or ".", suffix=".tmp")
    with handle:
        json.dump(state, handle, ensure_ascii=False, indent=1)
    os.replace(handle.name, STORE)


def all_for(day):
    """Every tick for one day, as {id: {done, at, by}}."""
    return _read().get(str(day), {})


def set_done(day, ticket_id, done, by=None):
    """Tick or untick one job. Returns the row as it now stands."""
    if not ticket_id:
        raise ValueError("a ticket needs an id, or nothing can be ticked twice")

    state = _read()
    day_state = state.setdefault(str(day), {})
    if done:
        day_state[ticket_id] = {
            "done": True,
            "at": datetime.now().isoformat(timespec="seconds"),
            "by": by,
        }
    else:
        day_state.pop(ticket_id, None)
    _write(state)
    return day_state.get(ticket_id, {"done": False})


def progress(day, total, done=None):
    """How much of the shift is behind them. Zero total is not an error.

    ``done`` should be the count of ticks that match a job on today's board.
    Falling back to the size of the store counts ticks for jobs that no longer
    exist, which reads as work nobody can see.
    """
    done = len(all_for(day)) if done is None else done
    return {"done": done, "total": total,
            "share": round(done / total, 2) if total else 0.0}
