"""A trading day, arriving.

The rest of this reads history. This is the other half: bills landing one at a
time while somebody watches, which is what the shop actually looks like and what
makes the autonomy legible. Nothing here is a special demo path. The feed
appends to the same file the agent reads, in the same format the till writes.

Two things had to be true for it to work at all.

Reading has to be cheap. Rebuilding a year of corrected history takes about
thirty seconds, so a page polling every two seconds cannot go near it. The live
read only touches bills appended since the feed started, which is a few hundred
lines, and leaves the cached history alone.

And appending has to be safe. The reader may be mid-file when a line arrives, so
every bill is written and flushed whole, and a half-written trailing line is
skipped rather than crashing the page.
"""

import json
import os
import random
import threading
import time
from datetime import date, datetime, timedelta

from ..core import catalogue
from ..simulation import generate
from ..ops import state
from ..core.receipts import Bill, Line, from_json, to_json

# Where the day starts from when a feed begins. Real trade, replayed fast.
DEFAULT_SPEED = 240          # 240x: a 12 hour day in three minutes


class Feed:
    """One replay, running in the background."""

    def __init__(self, path, speed=DEFAULT_SPEED, seed=None):
        self.path = path
        self.speed = max(1.0, float(speed))
        self.seed = seed
        self.offset = os.path.getsize(path) if os.path.exists(path) else 0
        self.started_at = None
        self.day = None
        self.written = 0
        self.total = 0
        self.clock = None            # where the shop is in its day
        self._stop = threading.Event()
        self._thread = None

    # ------------------------------------------------------------- running

    def start(self):
        if self._thread and self._thread.is_alive():
            return self
        self._stop.clear()
        self.day = self._next_day()
        bills, _ = generate.simulate(self.day, self.day,
                                     seed=self.seed if self.seed is not None
                                     else random.randrange(10_000))
        self.total = len(bills)
        self.written = 0
        self.started_at = time.monotonic()
        # Today is being written. Hold the corrected history where it is until
        # the day is done, or every page pays for a rebuild per bill.
        state.hold(True)
        self._thread = threading.Thread(target=self._run, args=(bills,),
                                        daemon=True)
        self._thread.start()
        return self

    def stop(self):
        self._stop.set()
        state.hold(False)
        return self

    @property
    def running(self):
        return bool(self._thread and self._thread.is_alive())

    def _next_day(self):
        """The day after the last one on file, so the history stays continuous."""
        last = None
        if os.path.exists(self.path):
            with open(self.path, encoding="utf-8") as handle:
                for line in handle:
                    if line.strip():
                        last = line
        if last:
            when = datetime.fromisoformat(json.loads(last)["at"]).date()
        else:
            when = date.today() - timedelta(days=1)
        day = when + timedelta(days=1)
        while day.weekday() == generate.CLOSED_WEEKDAY:
            day += timedelta(days=1)
        return day

    def _run(self, bills):
        opened = datetime.combine(self.day, generate.OPEN)
        for bill in bills:
            if self._stop.is_set():
                return
            # Where this bill sits in the trading day, compressed.
            due = (bill.at - opened).total_seconds() / self.speed
            waited = time.monotonic() - self.started_at
            if due > waited:
                if self._stop.wait(due - waited):
                    return
            self._append(bill)
            self.written += 1
            self.clock = bill.at
        state.hold(False)          # the day finished on its own

    def _append(self, bill):
        # One line, flushed, so a reader mid-file never sees half a bill.
        with open(self.path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(to_json(bill), ensure_ascii=False) + "\n")
            handle.flush()
            os.fsync(handle.fileno())

    # -------------------------------------------------------------- status

    def state(self):
        return {
            "running": self.running,
            "day": self.day.isoformat() if self.day else None,
            "speed": self.speed,
            "written": self.written,
            "expected": self.total,
            "shop_time": self.clock.strftime("%H:%M") if self.clock else None,
            "offset": self.offset,
        }


_feed = None


def get(path):
    global _feed
    if _feed is None or _feed.path != path:
        _feed = Feed(path)
    return _feed


def since(path, offset):
    """Bills appended after ``offset``, cheaply.

    Seeks straight to the byte and reads forward, so this costs the same whether
    the file holds a week or a decade behind it.
    """
    if not os.path.exists(path) or offset >= os.path.getsize(path):
        return []
    bills = []
    with open(path, encoding="utf-8") as handle:
        handle.seek(offset)
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                bills.append(from_json(json.loads(line)))
            except (json.JSONDecodeError, KeyError):
                # A trailing line still being written. It will be whole on the
                # next poll, two seconds from now.
                break
    return bills


def live(path, offset):
    """What today looks like so far, from the bills that have arrived.

    Deliberately does not touch the cached history. This is the number climbing
    on a screen while somebody watches, and it has to answer in milliseconds.
    """
    bills = since(path, offset)
    if not bills:
        return {"trading": False, "bills": 0, "rows": []}

    units, revenue, last_sold = {}, 0.0, {}
    for bill in bills:
        for line in bill.lines:
            units[line.item] = units.get(line.item, 0) + line.qty
            last_sold[line.item] = bill.at
            revenue += line.total

    rows = []
    for item, sold in units.items():
        product = catalogue.get(item)
        rows.append({"item": item, "sold": sold,
                     "revenue": round(sold * product.price, 2),
                     "last_at": last_sold[item].strftime("%H:%M")})
    rows.sort(key=lambda row: -row["sold"])

    return {
        "trading": True,
        "day": bills[0].day.isoformat(),
        "bills": len(bills),
        "customers": len(bills),
        "revenue": round(revenue, 2),
        "units": sum(units.values()),
        "average_basket": round(revenue / len(bills), 2),
        "from": bills[0].at.strftime("%H:%M"),
        "to": bills[-1].at.strftime("%H:%M"),
        "rows": rows,
    }
