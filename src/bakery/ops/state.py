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

from ..ops import paths
from ..core import analytics
from ..core import catalogue
from ..core import plan
from ..core.receipts import load

BILLS = paths.of("bills")
CACHE = paths.of("cache")

_state = None


class Shop:
    """One bakery's world: the bills, the index, and the corrected history."""

    def __init__(self, bills, index, history, corrected, source, stamp):
        self.bills = bills
        self.index = index
        self.history = history
        self.corrected = corrected
        self._by_day = None
        self.source = source
        self.stamp = stamp

    @property
    def demand_by_day(self):
        """The corrected history, keyed by day instead of by product.

        Anything measuring what a date did to trade has to read this and not the
        raw till. The till stops counting when the shelf is empty, so measuring
        an occasion from it reports the sell-out, not the occasion.
        """
        if self._by_day is None:
            table = {}
            for item, days in self.history.items():
                for day, units in days.items():
                    table.setdefault(day, {})[item] = units
            self._by_day = table
        return self._by_day

    @property
    def days(self):
        return sorted(self.index.units)

    @property
    def first_day(self):
        return self.days[0] if self.days else date.today()

    @property
    def last_day(self):
        return self.days[-1] if self.days else date.today()

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
    # Read the names first, then decide whether this shop's menu is already
    # known. Without this the whole thing only ever worked on the demo bakery:
    # a real till's first bill hit "not on the menu" and nothing loaded at all,
    # because learn() existed and nothing ever called it.
    bills = load(path, validate=False)
    _learn_menu_if_new(bills)
    for bill in bills:
        for line in bill.lines:
            catalogue.get(line.item)          # now there is a menu to check
    index = analytics.Index(bills)
    history, corrected = plan.corrected_history(bills, index=index)
    return bills, index, history, corrected


def _learn_menu_if_new(bills):
    """Derive the menu from the receipts when they are not the menu we hold.

    Deliberately conditional. When the bills already match, the catalogue in
    hand is kept, because it carries oven times, shelf lives and salvage values
    that no receipt can tell you and that a derived menu would flatten. When
    they do not match, nothing we hold applies to this shop anyway.
    """
    seen = {line.item for bill in bills for line in bill.lines}
    if not seen or seen <= set(catalogue.BY_NAME):
        return []
    learned = catalogue.learn(
        bills,
        food_cost=float(os.getenv("FOOD_COST", "0.30")),
        no_waste=[p.name for p in catalogue.PRODUCTS if p.bake_minutes <= 0]
    )
    catalogue.adopt(learned)
    catalogue.load_confirmed()          # any costs this shop already answered
    return [product.name for product in learned]


def ensure(path=None):
    """Make sure there is a shop to read.
    
    A fresh clone has no data. If the user wants the demonstration data, they can 
    run 'sonnabon-generate'. Otherwise, the application starts with a blank slate.
    """
    path = path or BILLS
    # On AWS the till export lives in S3. Keep a local copy current and read
    # that, so the cache and everything downstream work unchanged.
    from ..cloud import storage
    if storage.is_s3(path):
        return storage.local_copy(path, paths.home())
    if os.path.exists(path):
        return path
    
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        pass
        
    print(f"No trading data at {path}. Starting blank. "
          f"Run 'sonnabon-generate' to create the demonstration dataset.", flush=True)
    return path


_holding = False


def hold(on):
    """Stop rebuilding while the till is mid-day.

    Corrected history is history. A day still being written does not belong in
    it, and rebuilding a year on every appended bill costs about twenty seconds
    a call, which is enough to stall every page while trade is live. The live
    view reads only the bills that have arrived and never comes through here,
    so holding costs nothing and the day joins the history once it is complete.
    """
    global _holding
    _holding = bool(on)
    return _holding


def get(path=None, refresh=False):
    """The shop, built once. Cheap on every call after the first."""
    global _state
    path = ensure(path)

    if _holding and _state is not None and not refresh:
        return _state

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
                _learn_menu_if_new(_state.bills)
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
