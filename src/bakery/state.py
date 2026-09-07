"""Loaded once, reused everywhere.

Correcting a year of censored history takes about twenty seconds. Done inside an
agent turn that is a timeout; done once a night it is nothing. So it happens
here, behind a cache keyed on the data file's modification time, and every tool
reads through this module rather than touching the pile itself.

The cache invalidating on mtime rather than on a manual flag is deliberate. A
stale plan built on yesterday's corrections is the kind of bug that produces
plausible numbers for a week before anybody notices.
"""

import json
import os
import pickle
from datetime import date

from . import analytics, catalogue, plan
from .receipts import load

BILLS = os.getenv("BILLS_FILE", "data/bills.jsonl")
CACHE = os.getenv("BAKERY_CACHE", "data/.cache.pkl")

_state = None


class Shop:
    """One bakery's world: the bills, the index, and the corrected history."""

    def __init__(self, bills, index, history, corrected, source, stamp):
        self.bills = bills
        self.index = index
        self.history = history
        self.corrected = corrected
        self.source = source
        self.stamp = stamp

    @property
    def days(self):
        return sorted(self.index.units)

    @property
    def first_day(self):
        return self.days[0]

    @property
    def last_day(self):
        return self.days[-1]

    def summary(self):
        return {
            "source": self.source,
            "products": len(catalogue.PRODUCTS),
            "bills": len(self.bills),
            "trading_days": len(self.days),
            "from": self.first_day.isoformat(),
            "to": self.last_day.isoformat(),
            "corrected_days": sum(len(value) for value in self.corrected.values()),
        }


def _build(path):
    bills = load(path)
    index = analytics.Index(bills)
    history, corrected = plan.corrected_history(bills, index=index)
    return bills, index, history, corrected


def ensure(path=None):
    """Make sure there is a shop to read.

    A fresh clone has no data, because a year of receipts does not belong in
    version control. Generating it here means the first thing somebody runs
    works, instead of failing with a stack trace at whoever just cloned this.
    """
    path = path or BILLS
    if os.path.exists(path):
        return path
    from datetime import date, timedelta
    from . import generate
    print(f"No trading data at {path}. Generating a year, about 30 seconds.",
          flush=True)
    end = date.today()
    generate.write(end - timedelta(days=370), end, bills_path=path)
    return path


def get(path=None, refresh=False):
    """The shop, built once. Cheap on every call after the first."""
    global _state
    path = ensure(path)
    stamp = os.path.getmtime(path)

    if _state is not None and _state.source == path and _state.stamp == stamp \
            and not refresh:
        return _state

    if not refresh and os.path.exists(CACHE):
        try:
            with open(CACHE, "rb") as handle:
                cached = pickle.load(handle)
            if cached.get("source") == path and cached.get("stamp") == stamp:
                _state = Shop(cached["bills"], cached["index"], cached["history"],
                              cached["corrected"], path, stamp)
                return _state
        except Exception:
            # A corrupt cache must cost one rebuild, never the run. Falling
            # through here is the whole reason this is wrapped.
            pass

    bills, index, history, corrected = _build(path)
    _state = Shop(bills, index, history, corrected, path, stamp)
    os.makedirs(os.path.dirname(CACHE) or ".", exist_ok=True)
    with open(CACHE, "wb") as handle:
        pickle.dump({"source": path, "stamp": stamp, "bills": bills,
                     "index": index, "history": history,
                     "corrected": corrected}, handle)
    return _state


def today():
    """The shop's today, which is the day after its last bill.

    Demo data ends somewhere in the past, and an agent that thinks it is the
    real calendar date will forecast a year ahead and find no history. Anchoring
    to the data keeps every date in the run consistent.
    """
    return get().last_day
