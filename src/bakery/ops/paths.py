"""Where one shop's files live.

Every store here used to carry its own environment variable, and two carried
none at all: the outbox was written to a hard coded ``data/outbox.jsonl`` in two
different modules. Running a second bakery meant setting six variables correctly
and still being unable to move one of the files.

So there is one question now, ``SHOP_ID``, and every path follows from it. An
individual variable still wins where it is set, because a deployment that needs
the bills in S3 and everything else on local disk should not have to move
everything.

Unset, the layout is exactly what it was, so an existing checkout keeps working
and the demo needs no configuration at all.
"""

import os

# Which bakery this process is serving. One process, one shop: see `only()`.
SHOP = os.getenv("SHOP_ID", "").strip()
ROOT = os.getenv("DATA_ROOT", "data")

# Every file the system owns, and the variable that overrides each one.
STORES = {
    "bills": ("BILLS_FILE", "bills.jsonl"),
    "truth": ("TRUTH_FILE", "truth.json"),
    "cache": ("BAKERY_CACHE", ".cache.pkl"),
    "costs": ("COSTS_FILE", "costs.json"),
    "journal": ("JOURNAL_FILE", "journal.jsonl"),
    "tickets": ("TICKETS_FILE", "tickets.json"),
    "outbox": ("OUTBOX_FILE", "outbox.jsonl"),
    "team": ("TEAM_FILE", "team.json"),
    "notes": ("NOTES_FILE", "notes.md"),
}


def of(store):
    """The path for one store, honouring an explicit override."""
    try:
        variable, filename = STORES[store]
    except KeyError:
        raise KeyError(f"{store!r} is not a store. Known: {sorted(STORES)}")
    explicit = os.getenv(variable)
    if explicit:
        return explicit
    return os.path.join(ROOT, SHOP, filename) if SHOP else os.path.join(ROOT, filename)


def home():
    """The directory this shop's files live in."""
    return os.path.join(ROOT, SHOP) if SHOP else ROOT


def ensure():
    os.makedirs(home(), exist_ok=True)
    return home()


_serving = None


def only(shop=None):
    """Refuse to serve a second shop from this process.

    The catalogue, the loaded shop and the feed are all module level, which is
    the right shape for one process per bakery and a silent disaster for two:
    the second shop would quietly read the first one's menu and plan against it.
    Nothing about that failure looks like a failure, so it is asserted here
    rather than left to be discovered in somebody's production numbers.
    """
    global _serving
    shop = shop or SHOP or "demo"
    if _serving is None:
        _serving = shop
    elif _serving != shop:
        raise RuntimeError(
            f"This process is already serving {_serving!r} and cannot also "
            f"serve {shop!r}. The catalogue and the loaded shop are process "
            f"wide, so a second bakery here would read the first one's menu. "
            f"Run one process per shop.")
    return _serving


def describe():
    return {"shop": SHOP or "demo", "root": home(),
            "stores": {name: of(name) for name in STORES}}
