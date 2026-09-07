# The operations manager a small bakery cannot afford to hire

A bakery owner decides, from memory, at the end of a seventeen hour day, how
much of thirty things to make tomorrow. Then what to order from four suppliers
who each want it by a different hour. Then it resets and they do it again.

Nobody gets good at it, because there is never an hour to sit down with the
numbers. A small bakery keeps 4 to 9% of what it earns and throws away 10 to 15%
of what it makes.

This is one agent that does that job. You point it at the till, it reads the
bills, and from then on it decides tomorrow's production, orders against it,
watches the calendar, and emails the owner only when something genuinely needs
a person.

## The thing it knows that a till cannot

**Sales are not demand.** If the shop baked 40 croissants and sold all 40 by
10:14, the till says 40. Real demand might have been 65. Every sell-out
undercounts, and anything trained on that data learns to under-bake for ever,
settling on the shop's worst day.

The timestamps give it away. A product that stops selling dead while everything
else keeps going until closing time has run out, and that is provable from data
the shop already has. The agent learns each product's normal shape through the
day from days it did not run out, then on a day it did, works out how far
through that shape it got and scales up.

Everything downstream reads that corrected history, never the raw sales.

## What it does

- Reads the bills as they arrive: products, quantities, times
- Decides tomorrow's production and gives each person their own list
- Works back to ingredients and raises the orders against each supplier's cutoff
- Watches the calendar, so Halloween and Christmas arrive with the ingredients
  already ordered rather than three days late
- Says which products are growing and which are dying, and refuses to call it
  when the movement is inside the noise
- Emails the owner when something needs deciding, and stays quiet otherwise

Roughly twenty runs a week. One or two reach the owner.

## Measured, not claimed

The shop in `data/` is generated, and that is deliberate: it is the only way to
know the truth. No real till can tell you how many people wanted something and
left, so no real dataset can score a sell-out estimate. Here the demand is known
because it was generated first and then served out of a limited tray.

| What | Result |
|---|---|
| Sell-out detection | 87% precision, 74% recall |
| Demand estimate | 3.4% median error, within 20% on 97% of days |
| Lost margin over a year | Estimated 28,113 against a true 29,700, so 5% out |
| History needed | Three weeks. 90% precision on 18 trading days |
| Counterfactual over 120 days | Lost sales cut 53%, net cost down 7.7% |

Reproduce any of them:

```bash
python -m src.bakery.backtest        # would it have done better
```

## Running it

```bash
pip install -e .
python ui/app.py                     # generates a year on first run
```

Then open http://localhost:8000

The first start takes about half a minute: it generates the shop, then corrects
a year of censored history and caches it. Every start after that is instant.

## How it is built

One [Strands](https://strandsagents.com) agent with twelve tools and a Python
escape hatch, so anything the tools do not cover it writes and runs itself.

The limits are hooks, not prompt text. A ceiling written into a system prompt is
a request a model can argue itself out of; a hook that sets `event.cancel`
inside the agent loop is a control. Spend, looping and irreversible actions are
all gated that way.

The agent never sees a bill. There are 197,000 of them, which would cost more to
read once than the waste it is trying to prevent, and would not fit in context
anyway. Tools return tens of numbers, not thousands of rows.

```
src/bakery/
  receipts.py    bills, exactly as a till prints them
  catalogue.py   the menu, learned from the receipts themselves
  generate.py    a year of trade, with sell-outs on purpose and the truth kept
  analytics.py   sell-out detection, demand estimation, trends, rankings
  plan.py        corrected history, forecast, production quantities
  calendar.py    occasions, and how far ahead each has to be started
  team.py        whose job is what, and who confirms what ran out
  backtest.py    would it actually have done better
  tools.py       what the agent can do
  agent.py       the agent, and the limits it cannot argue with
  runs.py        what happens when the clock goes off
ui/
  app.py         the demo server
  index.html     five pages, one file
```

## Pointing it at a real shop

Nothing is hard-coded to the demo bakery. `catalogue.learn(bills)` derives the
menu from the receipts: names and prices come straight off the bill lines,
because a till already knows both.

The one thing a receipt cannot say is what an item cost to make, so that comes
from a single number the owner gives once. Applied to everything it makes every
product identical, which is wrong, so the agent tracks which costs it guessed
and asks about those. That list is the whole setup conversation: a few questions
the data actually raised.

Currency comes from the environment. Team names are placeholders.

## Licence

MIT.
