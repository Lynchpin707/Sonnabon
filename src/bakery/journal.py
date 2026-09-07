"""What Sonnabon did, in its own words.

Everything else here reports on the bakery. This reports on the agent, and it
exists because the product's central claim is that it works while nobody is
watching. A claim like that has to leave evidence, or the interface is asking to
be taken on trust.

One line per waking. When it woke, what woke it, what it decided, and whether it
judged the owner needed to hear about it. That last field is the one that
matters: an agent that reaches for a person constantly is a nuisance, and one
that never does is not to be trusted. The ratio is the product, so it is
measured rather than asserted.

Append-only, one JSON object per line, same shape as the till file. A run that
crashes half way leaves a short line and loses itself, not the week.
"""

import json
import os
from datetime import datetime, timedelta

from . import paths

PATH = paths.of("journal")

# Why it woke. Kept small on purpose: a vocabulary that grows every sprint stops
# being countable, and these are counted on the front page.
TRIGGERS = {
    "nightly": "close of trade",
    "weekly": "the week's review",
    "feed": "bills arriving",
    "asked": "you asked",
}


def already_said(key, within_days=7, path=None, now=None):
    """Has it already raised this exact thing recently.

    An overdue task does not stop being overdue, so without this the agent
    emails about the same late order every night until somebody does it. Saying
    a thing once and then trusting the person is the difference between an
    assistant and an alarm clock.
    """
    if not key:
        return False
    rows = [row for row in read(path) if row.get("key") == key]
    if not rows:
        return False
    latest = max(row["when"] for row in rows)
    reference = now or max(row["when"] for row in read(path))
    return (reference - latest) <= timedelta(days=within_days)


def record(kind, did, spoke=False, why=None, detail=None, cost_usd=0.0,
           tool_calls=0, path=None, at=None, key=None, figure=None):
    """Write one waking. Never raises: a journal that can break a run is worse
    than no journal, because it turns a bookkeeping problem into an outage."""
    entry = {
        "at": (at or datetime.now()).isoformat(timespec="seconds"),
        "kind": kind,
        "why": why or TRIGGERS.get(kind, kind),
        "did": did,
        "spoke": bool(spoke),
        "cost_usd": round(float(cost_usd), 4),
        "tool_calls": int(tool_calls),
    }
    if detail:
        entry["detail"] = detail
    if key:
        entry["key"] = key
    if figure:
        entry["figure"] = figure
    try:
        target = path or PATH
        os.makedirs(os.path.dirname(target) or ".", exist_ok=True)
        with open(target, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
            handle.flush()
    except OSError:
        pass
    return entry


def read(path=None, days=None):
    """Every waking on file, oldest first. A half-written trailing line is
    skipped rather than crashing the page that is reading it."""
    target = path or PATH
    if not os.path.exists(target):
        return []
    rows = []
    with open(target, encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
                row["when"] = datetime.fromisoformat(row["at"])
            except (json.JSONDecodeError, KeyError, ValueError):
                continue
            rows.append(row)
    if days is not None and rows:
        # Counted back from the most recent waking, not from the wall clock.
        # Runs are stamped in the shop's time, so a dataset a few days old would
        # otherwise report a week of silence when the week is simply behind us.
        cutoff = max(row["when"] for row in rows) - timedelta(days=days)
        rows = [row for row in rows if row["when"] >= cutoff]
    return rows


def summary(path=None, days=7):
    """The three figures on the header, each of them counted.

    ``spoke`` is deliberately not "messages sent". A single waking can send one
    email covering three decisions, and counting the decisions would inflate the
    number that is supposed to prove restraint.
    """
    rows = read(path, days=days)
    return {
        "days": days,
        "runs": len(rows),
        "spoke": sum(1 for row in rows if row["spoke"]),
        "cost_usd": round(sum(row.get("cost_usd", 0.0) for row in rows), 4),
        "tool_calls": sum(row.get("tool_calls", 0) for row in rows),
        "since": rows[0]["at"] if rows else None,
    }


def recent(path=None, limit=12):
    """Newest first, for the panel. Dates are left as strings for the page."""
    rows = read(path)[-limit:][::-1]
    for row in rows:
        row.pop("when", None)
    return rows
