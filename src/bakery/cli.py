"""The three things anyone actually runs.

These existed already, but only as a module path or a line of Python long
enough to mistype on stage. Naming them costs nothing and means the demo
runbook is three words rather than an incantation.
"""

import argparse
import sys
from datetime import date, timedelta

from . import paths


def serve(argv=None):
    """Start the site."""
    from ui import app
    app.serve()


def generate(argv=None):
    """Write a fresh year of trade, and the truth alongside it."""
    parser = argparse.ArgumentParser(
        prog="sonnabon-generate",
        description="Generate a bakery's trade, with demand kept aside so the "
                    "estimates can be scored against it.")
    parser.add_argument("--days", type=int, default=370,
                        help="how much history to write (default: 370)")
    parser.add_argument("--seed", type=int, default=None,
                        help="fix the shop, so a rerun is identical")
    args = parser.parse_args(argv)

    from . import generate as maker
    paths.ensure()
    end = date.today()
    bills = paths.of("bills")
    truth = paths.of("truth")
    maker.write(end - timedelta(days=args.days), end,
                bills_path=bills, truth_path=truth,
                **({"seed": args.seed} if args.seed is not None else {}))
    print(f"wrote {bills} and {truth}")


def backtest(argv=None):
    """Replay the year and price both plans against demand we know."""
    from . import backtest as run
    run.main()


def reset(argv=None):
    """Put the demo back to a known state: fresh trade, no ticks, no diary."""
    import os

    for store in ("bills", "truth", "cache", "journal", "tickets", "outbox",
                  "costs"):
        target = paths.of(store)
        if os.path.exists(target):
            os.remove(target)
            print(f"removed {target}")
    generate([])
    print("reset. Start the server and it will build the corrected history.")


if __name__ == "__main__":            # python -m src.bakery.cli generate
    which = {"serve": serve, "generate": generate, "backtest": backtest,
             "reset": reset}
    if len(sys.argv) < 2 or sys.argv[1] not in which:
        sys.exit(f"usage: python -m src.bakery.cli {{{'|'.join(which)}}}")
    which[sys.argv[1]](sys.argv[2:])
