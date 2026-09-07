"""Bills, exactly as a till prints them.

This is the only shape of data the agent is given. One bill, one moment, a few
lines. Everything the agent knows about demand it works out from a pile of
these, which is a real constraint and not a simplification: a small bakery has a
till and nothing else.

The field that matters most is the one owners never think about. ``at`` carries
the time, not just the date, and the time is what separates "we sold forty" from
"we ran out at ten past ten". Daily totals cannot tell those apart, and a
forecast that cannot tell them apart learns to under-bake for ever.
"""

import json
from dataclasses import dataclass, asdict
from datetime import datetime, date

from . import catalogue


@dataclass(frozen=True)
class Line:
    item: str
    qty: int
    unit_price: float

    @property
    def total(self):
        return round(self.qty * self.unit_price, 2)


@dataclass(frozen=True)
class Bill:
    number: int
    at: datetime
    lines: tuple
    payment: str = "card"

    @property
    def total(self):
        return round(sum(line.total for line in self.lines), 2)

    @property
    def items(self):
        return len(self.lines)

    @property
    def units(self):
        return sum(line.qty for line in self.lines)

    @property
    def day(self):
        return self.at.date()

    def qty_of(self, item):
        return sum(line.qty for line in self.lines if line.item == item)


def to_json(bill):
    record = asdict(bill)
    record["at"] = bill.at.isoformat(timespec="seconds")
    record["lines"] = [asdict(line) for line in bill.lines]
    return record


def from_json(record):
    return Bill(
        number=record["number"],
        at=datetime.fromisoformat(record["at"]),
        lines=tuple(Line(**line) for line in record["lines"]),
        payment=record.get("payment", "card"),
    )


def save(bills, path):
    """One bill per line. A day's trade appends without rewriting the file, and
    a half-written file loses one bill rather than the month."""
    with open(path, "w", encoding="utf-8") as handle:
        for bill in bills:
            handle.write(json.dumps(to_json(bill), ensure_ascii=False) + "\n")


def load(path, validate=True):
    """Read bills back, and refuse unknown products at the door.

    ``validate`` is off for exactly one caller: the first read of a shop whose
    menu is not known yet, which has to see the item names before it can learn
    them. Everything after that validates, because by then there is a menu to
    validate against.

    Validating here is deliberate. An item name that is not on the menu has no
    price and no cost, so every margin computed from it would be wrong while
    looking perfectly reasonable. Better to stop on the first bad line than to
    hand somebody a confident number built on a typo.
    """
    bills, seen, report = [], set(), {"duplicates": 0, "gaps": []}
    previous = None
    with open(path, encoding="utf-8") as handle:
        for position, raw in enumerate(handle, start=1):
            raw = raw.strip()
            if not raw:
                continue
            bill = from_json(json.loads(raw))
            if validate:
                for line in bill.lines:
                    catalogue.get(line.item)  # raises with the menu attached

            # A till that is retried, or an adapter that replays a webhook,
            # sends the same bill twice. Counting it twice would inflate every
            # figure downstream by a little, which is the worst size of error:
            # large enough to matter and small enough to look plausible.
            if bill.number in seen:
                report["duplicates"] += 1
                continue
            seen.add(bill.number)

            # A jump in the numbering means bills did not arrive. That is not
            # an error here, because the shop may simply have voided some, but
            # it is the difference between a quiet day and a broken feed, and
            # nobody can tell those apart after the fact.
            if previous is not None and bill.number > previous + 1:
                report["gaps"].append((previous, bill.number))
            previous = max(previous or 0, bill.number)

            bills.append(bill)

    load.last_report = report
    return bills


load.last_report = {"duplicates": 0, "gaps": []}


def intake_report():
    """What the last read of the till file noticed. Empty is the good answer."""
    report = dict(load.last_report)
    report["missing"] = sum(b - a - 1 for a, b in report["gaps"])
    return report


def days(bills):
    """Every trading day present, in order. Days with no bills do not appear,
    which is correct: a closed Monday is not a Monday that sold nothing, and
    averaging the two together would drag every forecast down."""
    return sorted({bill.day for bill in bills})


def units_by_day(bills):
    """{date: {item: units}}. The workhorse behind most of the analytics."""
    table = {}
    for bill in bills:
        row = table.setdefault(bill.day, {})
        for line in bill.lines:
            row[line.item] = row.get(line.item, 0) + line.qty
    return table
