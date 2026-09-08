# The demo, start to finish

Five minutes. One story, told in order, with nothing on screen that is not
part of it.

The whole thing turns on one sentence. Everything before it is setup and
everything after it is proof:

> **Your best days are your worst days.**

---

## Before you record

**1. Reset to a known state.** The demo must be identical every run, or a retake
looks like a different product.

```bash
rm -rf data/                      # bills, ticks, cache
python -c "from datetime import date, timedelta; from src.bakery import generate; \
end = date.today(); generate.write(end - timedelta(days=370), end)"
```

**2. Warm it.** The first read builds a year of corrected history and takes
about thirty seconds. Do it now, not on camera.

```bash
sonnabon                          # wait for "listening on"
```

**3. Have these ready in tabs**

| | |
|---|---|
| The app | <http://localhost:8000> |
| A real receipt | the photo of an actual bakery bill, for four seconds |
| A terminal | for the backtest, at the end |

**4. Check the three numbers are on screen** before you hit record: customers,
taken, and the count of things that ran out. If `ran out` is zero, the story has
no subject. Pick a different day with `?on=`.

---

## The five minutes

### 0:00 · The counter (20s)

Open on the shop, not the software. A real counter at closing time and what is
still sitting on it.

> "A small bakery keeps four to nine percent of what it earns, and throws away
> ten to fifteen percent of what it makes."

Then the receipt photo for four seconds.

> "This is everything it knows about its own trade. A pile of these."

### 0:20 · The burden (25s)

> "Nine products. Every night, from memory, at the end of a seventeen hour
> day. Then four suppliers who each want their order by a different hour.
> Nobody gets good at it, because there is never an hour to sit down with the
> numbers."

### 0:45 · Hiring it (30s)

Show the app. Type into the brief bar and send:

```
Read today, plan tomorrow, and email me only if something needs deciding.
```

Let the run stream. Point at the tool calls going past.

> "You brief it once. After that it wakes on its own: close of trade, before the
> night shift, at every supplier cutoff."

### 1:15 · The reversal (60s) ← **the centre of the film**

Point at the day's figures. Then at the two pink bars.

> "Sold out. Which looks like a good day."

Scroll to the sell-out chart.

> "The solid line is what sold. It stops dead at 12:51. The dashed line is what
> a normal day would have done, and it keeps going. **About a hundred and
> thirty-two people wanted one. Sixty got one.** The other seventy-two looked at
> an empty tray and left, and the till recorded a triumph."

Pause. Then:

> "A till can only count what leaves the shelf. It has no way to count the
> people who wanted something that was not there. So the loss is not just
> invisible, it is filed as a success, and next year the shop bakes sixty
> again."

### 2:15 · What it does about it (45s)

Tomorrow's bake list.

> "It corrects for that before it forecasts. Cheap things get made past the
> point of certainty, because running out costs more than binning does.
> Expensive things do not. Most owners believe the opposite."

Then the board.

> "Each person gets their own list. And whoever is on the counter gets one job:
> confirm what ran out. It worked that out from the timestamps and says so.
> Only somebody standing there can settle it, and their tick makes tomorrow
> better."

Tick one. It saves to the server, not the browser.

### 3:00 · The planning half (40s)

The Diary tab.

> "Halloween is fifty-four days away. The ingredient order is due on the tenth
> of October, because the supplier needs three weeks for a quantity change.
> That is the job nobody does, because the shop deciding tonight's bake at
> twenty to nine is not also thinking about October."

### 3:40 · It is actually live (35s)

Start the feed, then talk over it while the numbers climb.

```bash
curl -X POST localhost:8000/api/feed -H "Content-Type: application/json" \
     -d '{"action":"start","speed":240}'
```

> "Nobody is typing. That is the till selling, one bill at a time, into the same
> file the agent reads. Twelve hours in three minutes."

Let a bar turn pink on camera if you can time it.

### 4:15 · The proof (30s)

Terminal.

```bash
sonnabon-backtest
```

> "We replayed a hundred and twenty days and priced both plans against demand we
> actually know, because the shop is simulated and that is the only way to know
> it. **Lost sales fall from eight thousand three hundred to three thousand
> seven hundred.** Waste goes up, which is correct: it buys availability with
> flour. Net it saves about five thousand a year."

### 4:45 · Close (15s)

> "It wakes every night and reaches the owner on eight nights in thirty. The
> other twenty-two it handles alone, and the diary shows every one of them. It
> costs less than one unsold cake a week. That ratio is the product."

---

## What to say about the data, if asked

Do not apologise for it. It is the method:

> "We generated a year of trade so the truth would be knowable. No real till can
> tell you how many people wanted something and left, so no real dataset can
> score a sell-out estimate. Ours can: 91% detection precision, 3.0% median
> error, and a yearly total within 7% of the truth."

---

## If something breaks

| | |
|---|---|
| Page says "cannot reach the shop" | The server is not up, or still warming. Wait for "listening on" |
| Everything reads zero | `data/` was deleted and not regenerated. See step 1 |
| The agent run fails | No model configured. Run `ollama pull qwen3`, or set AWS_REGION and credentials. The read-only views still show every number |
| The feed does nothing | It appends from the day *after* the last one on file. Check `GET /api/live` |
| Nothing ran out today | Pick another day: `/api/today?on=2026-09-05` |
| A tab will not open on reload | Each page has its own address now, `#today`, `#diary` and so on |

---

## What is deliberately not in the five minutes

Cut these even though they work, because they cost more time than they earn:

- The Reports tab and the printable week
- Best sellers three ways
- The cost ledger and the tier split
- Trends, unless you have a spare twenty seconds at 3:40

They belong in the README and the repo, where a judge who wants them will look.
