"""What Sonnabon has learned about this particular shop.

The receipts say what sold. They do not say that the Tuesday market takes forty
croissants, that the pistachio supplier needs three weeks rather than one, or
that Luca is away every August. Those things are learned once, from the owner or
from a run that noticed them, and they have to survive the run that learned them
or they are learned again every night.

So they live in a markdown file the owner can open, read and correct. Markdown
rather than JSON on purpose: the point is that a person can see what the agent
believes about their shop and cross a line out when it is wrong. An agent whose
memory cannot be inspected is an agent that quietly becomes wrong.

One note per line, dated, under a heading. Nothing is ever silently rewritten:
the agent appends, and the owner edits.
"""

import os
import re
from datetime import date

from . import paths

# The headings a note can go under. Kept short and fixed: an agent inventing a
# new heading every run produces a file nobody can scan.
SECTIONS = (
    "The shop",           # hours, staff, oven, anything structural
    "Products",           # what a product is really like to make or sell
    "Suppliers",          # lead times, minimums, who needs what notice
    "Occasions",          # what actually happened last year, in this shop
    "Corrections",        # where the owner said the agent was wrong
)

HEADER = """# What I know about this shop

Sonnabon wrote this. Edit it freely: it is read at the start of every run and
whatever it says is treated as true. Crossing out a wrong line is how you
correct the agent.
"""


def path():
    return paths.of("notes")


def read():
    """The whole file as text. Empty string when there is nothing yet."""
    target = path()
    if not os.path.exists(target):
        return ""
    try:
        with open(target, encoding="utf-8") as handle:
            return handle.read()
    except OSError:
        return ""


def sections():
    """The file parsed back into {heading: [note, ...]}.

    Parsing its own output rather than keeping a second copy in JSON. The file
    is the record, so whatever a person leaves in it is what the agent reads.
    """
    found = {}
    heading = None
    for line in read().splitlines():
        match = re.match(r"^##\s+(.*)", line)
        if match:
            heading = match.group(1).strip()
            found.setdefault(heading, [])
            continue
        if heading and line.strip().startswith("- "):
            # Drop the trailing date marker. Without this the note read back
            # carries "_2026-09-10_" and never matches the note going in, so
            # the duplicate guard never fires.
            text = line.strip()[2:].strip()
            text = re.sub(r"\s*_\d{4}-\d{2}-\d{2}_\s*$", "", text)
            found[heading].append(text.strip())
    return found


def remember(note, section="The shop", on=None):
    """Add one thing learned. Refuses a duplicate rather than repeating it."""
    note = " ".join(str(note).split())
    if not note:
        raise ValueError("An empty note is not something learned.")
    if section not in SECTIONS:
        raise ValueError(f"{section!r} is not a section. Use one of "
                         f"{list(SECTIONS)}.")

    already = sections().get(section, [])
    if any(note.lower() == seen.lower() for seen in already):
        return {"added": False, "why": "already known", "note": note}

    stamp = (on or date.today()).isoformat()
    body = read() or HEADER

    line = f"- {note}  _{stamp}_"
    marker = f"## {section}"
    if marker in body:
        # Append under the existing heading, before the next one.
        start = body.index(marker) + len(marker)
        nxt = body.find("\n## ", start)
        cut = len(body) if nxt == -1 else nxt
        body = body[:cut].rstrip("\n") + "\n" + line + "\n" + body[cut:]
    else:
        body = body.rstrip("\n") + f"\n\n{marker}\n\n{line}\n"

    paths.ensure()
    with open(path(), "w", encoding="utf-8") as handle:
        handle.write(body)
    return {"added": True, "section": section, "note": note, "on": stamp}


def forget(fragment):
    """Remove every note containing this text. The owner's override."""
    fragment = fragment.strip().lower()
    if not fragment:
        raise ValueError("Refusing to match every line.")
    kept, dropped = [], 0
    for line in read().splitlines():
        if line.strip().startswith("- ") and fragment in line.lower():
            dropped += 1
            continue
        kept.append(line)
    if dropped:
        with open(path(), "w", encoding="utf-8") as handle:
            handle.write("\n".join(kept).rstrip("\n") + "\n")
    return {"removed": dropped}


def summary(limit=40):
    """What to put in front of the model at the start of a run.

    Capped, because this is prepended to every run and an unbounded file would
    quietly become the largest thing the agent reads.
    """
    found = sections()
    total = sum(len(v) for v in found.values())
    if not total:
        return {"known": 0, "notes": {},
                "note": "Nothing learned about this shop yet."}
    trimmed, left = {}, limit
    for heading in SECTIONS:
        rows = found.get(heading) or []
        if not rows or left <= 0:
            continue
        trimmed[heading] = rows[-left:][:left]
        left -= len(trimmed[heading])
    return {"known": total, "notes": trimmed, "file": path()}
