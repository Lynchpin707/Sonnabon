"""A shift running on its own: work getting ticked, and the agent waking at close.

The feed replays the till. This is everything else that happens around it while
nobody is watching, and it exists because "runs on its own" was the central
claim and nothing in the system actually ran on its own. Every run had to be
started by pressing a button, which is not autonomy, it is a remote control.

So this watches the shop clock the feed is keeping and acts on it:

    the bakers finish their trays through the morning
    whoever is on the counter confirms what ran out, near close
    at close of trade the agent wakes by itself and plans tomorrow

Nothing here is a special demo path. The ticks go through the same store the
board writes to, and the run is the same ``runs.nightly`` the scheduler would
invoke on a real shop. What is simulated is the passage of time, not the work.
"""

import threading
import time
from datetime import datetime, time as clock

from . import feed, journal, runs, state, team

# When each kind of work lands in the day. Bakers are finishing trays from
# before opening; the counter can only confirm a sell-out once the day is
# nearly done, because until then it might still just be a slow morning.
BAKE_DONE_BY = clock(9, 30)
CONFIRM_AFTER = clock(18, 0)

# How often the shift looks at the clock. Fast enough to land on the right
# minute of a compressed day, slow enough to cost nothing.
TICK_SECONDS = 1.0


class Shift:
    """One trading day, minding itself."""

    def __init__(self, stream=None, on_event=None):
        self.stream = stream or feed.get(state.BILLS)
        self.on_event = on_event
        self.ticked = []
        self.woke = None
        self.board = {"board": []}
        self.day = None
        self._stop = threading.Event()
        self._thread = None

    # ------------------------------------------------------------- running

    def start(self):
        if self._thread and self._thread.is_alive():
            return self
        self._stop.clear()
        self.ticked, self.woke = [], None
        # The day's jobs are settled before it opens, so the board is read once
        # here rather than on every tick. Reading it mid-day used to rebuild a
        # year of corrected history per call and the shift never got past it.
        self.board = team.today()
        self.day = state.today()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        return self

    def stop(self):
        self._stop.set()
        return self

    @property
    def running(self):
        return bool(self._thread and self._thread.is_alive())

    def _say(self, **event):
        if not self.on_event:
            return
        try:
            self.on_event(event)
        except Exception:
            self.on_event = None          # a viewer left; the shift carries on

    def _run(self):
        done_bakes = False
        confirmed = False

        while not self._stop.is_set():
            if not self.stream.running and self.stream.written == 0:
                # The till has not started yet. Wait rather than assume a time.
                if self._stop.wait(TICK_SECONDS):
                    return
                continue

            now = self.stream.clock
            if now is None:
                if self._stop.wait(TICK_SECONDS):
                    return
                continue

            if not done_bakes and now.time() >= BAKE_DONE_BY:
                done_bakes = True
                self._tick(kind="bake", by="the bakers")

            if not confirmed and now.time() >= CONFIRM_AFTER:
                confirmed = True
                self._tick(kind="check", by="the counter")

            # The till has stopped writing and the day is over. This is close of
            # trade, which is when the agent is supposed to wake without being
            # asked.
            if not self.stream.running and self.stream.written:
                self._close()
                return

            if self._stop.wait(TICK_SECONDS):
                return

    # --------------------------------------------------------------- doing

    def _tick(self, kind, by):
        """Mark one kind of work done, through the same store the board uses."""
        marked = 0
        day = self.day
        for person in self.board["board"]:
            for job in person["jobs"]:
                if job["kind"] != kind or job["done"]:
                    continue
                team.set_done(day, job["id"], True, by)
                marked += 1
                for row in job.get("detail", ()):
                    team.set_done(day, row["id"], True, by)
                    marked += 1
        if marked:
            self.ticked.append({"kind": kind, "by": by, "jobs": marked})
            self._say(kind="ticked", what=kind, by=by, jobs=marked)

    def _close(self):
        """Close of trade. The agent wakes on its own and plans tomorrow."""
        self._say(kind="closing")
        try:
            result = runs.nightly()
        except Exception as error:
            # A failed run must not take the shift with it, and must not be
            # silent either: a night that produced nothing is a fact.
            journal.record("nightly", f"Woke at close and could not finish: "
                                      f"{error}", spoke=False,
                           why="close of trade")
            self._say(kind="failed", error=str(error))
            return
        self.woke = {"spoke": result["speaks"],
                     "units": result["plan"]["units"],
                     "at": datetime.now().isoformat(timespec="seconds")}
        self._say(kind="woke", spoke=result["speaks"],
                  units=result["plan"]["units"])

    # -------------------------------------------------------------- status

    def state(self):
        return {
            "running": self.running,
            "shop_time": (self.stream.clock.strftime("%H:%M")
                          if self.stream.clock else None),
            "ticked": list(self.ticked),
            "woke": self.woke,
        }


_shift = None


def get(stream=None, on_event=None):
    global _shift
    if _shift is None:
        _shift = Shift(stream=stream, on_event=on_event)
    if on_event is not None:
        _shift.on_event = on_event
    return _shift
