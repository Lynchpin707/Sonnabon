"""Which jobs are done.

The board is not a printout, it is a thing people tick as the shift goes. That
state has to live on the server: two people share a kitchen, they are not on the
same phone, and a checkbox that only exists in one browser is decoration.

Deliberately a file rather than a database. One small shop generates a handful
of ticks a day, a file is atomic enough at that rate, and it means somebody can
open it and see what happened without installing anything. Swap in DynamoDB when
there is a second shop, not before.
"""

import json
import os
import tempfile
from datetime import datetime

STORE = os.getenv("TICKETS_FILE", "data/tickets.json")


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


def progress(day, total):
    """How much of the shift is behind them. Zero total is not an error."""
    done = len(all_for(day))
    return {"done": done, "total": total,
            "share": round(done / total, 2) if total else 0.0}
