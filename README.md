# Sonnabon

**Operations and planning, for small bakeries.**

Sonnabon takes three things off a bakery owner.

**The time.** Deciding tomorrow's production and placing the ingredient orders
is roughly an hour a day, at the end of a seventeen hour one. It happens after
close, tired, from memory.

**The maths that never gets done.** How much of each thing to make is a real
calculation, and no small shop does it. There is no hour to sit down with the
numbers, and nobody was ever taught which numbers to look at.

**The planning that gets left too late.** Christmas needs flour ordered three
weeks out and a trial batch two weeks before that. A shop deciding tonight's
bake at twenty to nine is not also thinking about October, so occasions arrive
three days early with an apology.

One [Strands](https://strandsagents.com) agent. Point it at the till once. From
then on it decides tomorrow's production, orders the ingredients, holds the
calendar, and emails the owner only when something genuinely needs a person.

Ask it anything from any page. It answers in place and shows its working.

![The day so far](docs/shots/today.png)

---

## Why the maths is harder than it looks

A till records what left the shelf. It cannot record what somebody wanted and
did not find.

So a day where the tiramisu sold out at 12:51 looks, in the data, like a good
day: sixty sold, nothing left over. About a hundred and thirty-two people wanted
one. The other seventy-two are not in the file anywhere.

That matters because every forecast is built on that file. Trained on sales, a
forecast learns to under-bake, and it gets worse every year: less made, sells
out sooner, records an even lower number.

**The timestamps are the way out.** A product that stops selling dead while
everything else keeps going has run out, and that is provable from data the shop
already has. Sonnabon learns each product's normal shape through the day from
days it did not run out, then on a day it did, works out how far through that
shape it got and scales up.

Everything downstream reads that corrected history, never the raw sales. That
one step is what the rest of it rests on.

It is also why the occasion lifts are measured off corrected demand and not off
sales. Measured off the till, Christmas looks like a 1.6x week. Measured off
what people actually wanted, it is 3.8x. A shop planning from the till would
under-bake Christmas by more than half and the till would report a triumph.

![The plan, and what the till could not tell you](docs/shots/sellout.png)

The solid line is what sold. It stops dead at 12:51. The dashed line is what a
normal day would have done, and it carries on. The gap between them is
seventy-two people that nothing in the shop could have counted, and €233 of
margin that left with them.

On the left, tomorrow's numbers, already raised because of it. And the one thing
that genuinely needs a person: Halloween is fifty-five days away, and the answer
changes what gets ordered.

## What it does

| | |
|---|---|
| **Every evening** | Reads the day, decides tomorrow's production, gives each person their own list |
| **Per supplier cutoff** | Works back to ingredients and raises the orders |
| **Every week** | Says what is growing and what is dying, and refuses to call it when the movement is noise |
| **Weeks ahead** | Holds the occasion calendar, so Christmas arrives with the flour already ordered |
| **From your own tills** | Measures what each occasion actually did here last year, rather than assuming |
| **Rarely** | Emails the owner, when something actually needs deciding |
| **On demand** | Answers whatever you ask it, from the button on any page |

**It speaks on 8 nights in 30, and stays quiet on the other 22.** That ratio is
the product, and it is measured rather than asserted: a run earns an email by
being unusual for this shop, not by clearing a fixed number every shop clears
most days. A late task is raised once, not once a night.

Sonnabon keeps its own diary, so the ratio is on the page rather than in a
sentence. Every waking writes a line, including the quiet ones.

![Sonnabon's diary](docs/shots/diary.png)

![The board](docs/shots/board.png)

The board splits the night's work by who starts when. The person on the counter
gets one job: confirm what ran out. Sonnabon inferred it from the timestamps and
says so; only somebody standing there can settle it, and their tick makes the
next forecast better.

## Measured, not claimed

The shop in `data/` is generated, and that is the point. **No real till can say
how many people wanted something and left**, so no real dataset can score a
sell-out estimate. Here demand is known, because it was generated first and then
served out of a limited tray.

| | |
|---|---|
| Sell-out detection | **91%** precision, 80% recall |
| Demand estimate | **3.0%** median error, within 20% on 99% of 649 days |
| Lost margin over a year | Estimated 27,618 against a true 29,566 |
| History needed | **Three weeks.** 94% precision on 18 trading days |
| Counterfactual, 120 days | **Lost sales cut 56%**, net cost down 10.8% |

```bash
python -m src.bakery.backtest    # replays the year and prices both plans
pytest                           # 51 tests: the maths, and the site
```

The counterfactual is worth reading in full. Over 120 days Sonnabon's waste goes
**up**, from 9,912 to 12,579, and its lost sales go **down from 8,321 to 3,690**,
because running out costs more than binning does. Net it saves 1,964, or about
5,000 a year, and it is better on 65 days of 120. That is the newsvendor doing
what it should, and it is visible in the numbers rather than asserted.

## Run it

```bash
pip install -e .
python ui/app.py
```

Open <http://localhost:8000>. The first start generates a year and corrects it,
about thirty seconds. Every start after that is instant.

### The look

The background is a fragment shader: vertical stripes with a slow wave through
them, which is an awning rather than a pattern. Panels are glass over it.

Headings are set in **Super Bakery**, which is free for personal and commercial
use. Its licence ships beside it in `ui/assets/` so the repo carries its own
proof rather than a claim. Every figure on the page is set in the text face
instead, because a display font is lovely on a name and unreadable on a column
of numbers.

The two images in `ui/assets/` are placeholders and are not committed. Drop your
own `logo.jpg` and `fab.png` in and the page picks them up.

## How it is built

```
src/bakery/
  receipts.py    bills, exactly as a till prints them
  catalogue.py   the menu, learned from the receipts themselves
  generate.py    a year of trade, sell-outs on purpose, truth kept aside
  analytics.py   sell-out detection, demand estimation, trends, rankings
  plan.py        corrected history, forecast, production quantities
  calendar.py    occasions, and how far ahead each has to be started
  team.py        whose job is what, whether it is done, who confirms sell-outs
  feed.py        a trading day arriving live, one bill at a time
  journal.py     what it did and when, so the autonomy is evidence not a claim
  state.py       loaded once, cached on the data file's timestamp
  backtest.py    would it actually have done better
  tools.py       the thirteen things the agent can do
  agent.py       the agent, and the limits it cannot argue with
  runs.py        what happens when the clock goes off
ui/
  app.py         the demo server
  index.html     five pages, one file, no build step
```

**The limits are hooks, not prompt text.** A ceiling written into a system
prompt is a request a model can talk itself out of. A hook that sets
`event.cancel` inside the agent loop is a control. Spend, looping and
irreversible actions are all gated that way.

**It reads summaries, samples, or code. Never the pile.** There are 149,000
bills. The arithmetic decides the architecture:

| Reading | Tokens | Cost per read |
|---|---|---|
| One day, raw | 31,000 | $0.09 |
| One week, raw | 196,000 | $0.59, and past the context window |
| One week, summarised | 4,000 | $0.01 |

So tools return tens of numbers rather than thousands of rows. When a summary is
not enough, `sample_bills` returns fifteen real receipts, spread across the day
or clustered around an hour, for about 200 tokens. When the question needs every
bill, `run_python` runs over all of them and returns the answer instead of the
data.

That is why a month of running Sonnabon costs a few dollars, and why the cost
per shop stays flat however long the shop has been trading.

## Pointing it at a real shop

Nothing is hard-coded to the demo bakery.

`catalogue.learn(bills)` derives the menu from the receipts. Names and prices
come straight off the bill lines, because a till already knows both.

The one thing a receipt cannot say is what an item cost to make. That comes from
a single number the owner gives once, and applied to everything it makes every
product identical, which is wrong. So Sonnabon tracks which costs it guessed and
asks about those. **That list is the whole setup conversation:** a few questions
the data actually raised, rather than a form.

Currency, data paths and limits are all environment variables. See
[`.env.example`](.env.example).

## What is honest about it

- The shop is simulated. Stated everywhere, and it is why the numbers above can
  exist at all.
- The backtest's corrections are learned from the whole file, so a little future
  leaks into the past. The forecasts themselves only read days before the one
  they plan. The tool prints this caveat rather than burying it.
- Web search returns "not configured" without an API key instead of inventing an
  event.
- Purchase orders and emails go to `data/outbox.jsonl` until SES is set up.
- The artwork is a placeholder and is not committed. The font is, along with its
  licence.

## Licence

MIT.
