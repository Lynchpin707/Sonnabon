# Sonnabon

**Operations and planning, for small bakeries.**

A small bakery cannot afford an operations manager or a planner, so the owner is
both, late at night, from memory. Sonnabon does that job.

**Operations.** It reads the till and works out what to make tomorrow, product
by product, from the statistics an owner has no evening to sit down with.

**Planning.** It holds the calendar, works backwards from each occasion to the
day the ingredients have to be ordered, hands each person their list, and looks
outward for the markets and fairs worth taking a stall at.

It runs on its own and emails the owner only when there is a decision that needs
a person.

Point it at the till once. It does not need setting up again.

Built on the [Strands Agents SDK](https://strandsagents.com). One agent, eighteen
tools, and its limits enforced as SDK hooks rather than as prompt text. Runs on
Amazon Bedrock, or on a local model, whichever is configured.

*AWS Agents for Humans, Professional Agents track.*

![The day so far](docs/shots/today.png)

The bar across the top is where the first prompt goes. You brief it on the shop
once, the way you would a manager you had just hired, and it works from there.
The chef in the corner opens the same thing from any page.

## The two halves of the job

**The maths that does not get done.** How much of each thing to make is a real
calculation, and a counterintuitive one: cheap things should be made past the
point of certainty because running out costs more than binning does, and
expensive things should not. Most owners believe the opposite. It happens after
close, tired, from memory, and nobody was taught which numbers to look at.

**The planning that gets left too late.** Christmas needs flour ordered weeks
out and a trial batch before that. A shop deciding tonight's bake at twenty to
nine is not also thinking about October, so occasions arrive with no time left
to prepare for them, and the market whose applications closed in August is
simply missed.

It does not replace the owner. It does the part that is arithmetic and the part
that is a calendar, and it stays quiet otherwise.

## Setting it up is one kind of question, asked once

Everything about the shop comes off the receipts. Names, prices, how fast each
thing sells, what ran out and when. Nothing is typed in.

The one thing a receipt cannot say is what something cost to make, and cost is
what decides how much gets baked. So Sonnabon guesses from a single food cost
ratio, marks every guess, and asks about those and nothing else. Correct one and
the service level moves while you watch.

**That list is the whole setup.** A few questions the data actually raised,
rather than a form.

![Setup: what it worked out, and what it has to ask](docs/shots/setup.png)

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

Everything downstream reads that corrected history, never the raw sales.

![What the till could not tell you](docs/shots/sellout.png)

It is also why occasion lifts are measured off corrected demand rather than off
sales. Measured off the till, Christmas looks like a 1.5x week. Measured off
what people actually wanted, it is 3.5x. A shop planning from the till would
under-bake Christmas by more than half, and the till would report a triumph.

## It hands out the work and tracks it

![The board](docs/shots/board.png)

A decision that stays in a report is not a decision. Sonnabon turns the night's
plan into tickets, splits them by who starts when, and tracks what has actually
been done. Ticks live on the server, not in one person's browser, because two
people share a kitchen and are not on the same phone.

The owner's column is empty on purpose. Work landing back on them is the thing
this exists to stop, so the calendar's run-up tasks go to whoever does them and
only reach the owner when a decision needs making.

The person on the counter gets one ticket: confirm what ran out. Sonnabon
inferred it from the timestamps and says so; only somebody standing there can
settle it, and their tick makes the next forecast better.

The loop closes both ways. `team_board` is one of its tools, so it reads back
what was actually ticked: a sell-out somebody confirmed is a fact it can lean
on, one nobody confirmed is still its own inference, and it knows the
difference when it speaks. If the confirmations stop coming back the numbers
get weaker every night, and that is something it can raise.

## Watch a day run itself

Press **Start the till** on the day card. Bills replay into the same file the
agent reads, one at a time, at 240 times real speed, and the figures climb with
the shop clock beside them.

The rest happens without anybody pressing anything. The bakers finish their
trays through the morning and the board ticks. Near close, whoever is on the
counter confirms what ran out. At close of trade the agent wakes by itself,
reads the day, plans tomorrow, and decides whether the owner needs to hear
about it. The diary gains a line either way.

That is the whole claim, running in about three minutes.

## You can see what it did while you were not looking

![Sonnabon's diary](docs/shots/diary.png)

Every time it wakes it writes a line, including the quiet ones. **It speaks on 8
nights in 30 and handles the other 22 alone.** A run earns an email by being
unusual for this shop, not by clearing a fixed number every shop clears most
days, and a late task is raised once rather than once a night.

That ratio is the product, so it is on the page rather than in a sentence.

## How the estimate was checked

The shop in `data/` is generated. No real till can say how many people wanted
something and left, so no real dataset can score a sell-out estimate. This one
can, because demand was decided first and then served out of a limited tray.

Against that known demand the estimate lands within 3% of the truth on the
median day, and the detector finds a real sell-out nine times in ten. Three
weeks of history is enough to start.

```bash
uv run sonnabon-backtest    # replays the year and prices both plans
uv run pytest               # 71 tests: the maths, and the site
```

The backtest is the interesting one. Waste goes **up** and lost sales go **down
by more than half**, because running out costs more than binning does, which
most owners believe the other way round.

## Run it

Using `uv`, you can run the application directly in two ways:

**1. Normal usage (Blank slate)**
Start the server without any trading history. You can then point it at your own data.
```bash
uv run sonnabon
```

**2. Demonstration mode**
To populate the shop with a year of simulated trading data before starting:
```bash
uv run sonnabon-generate    # a fresh year of trade, --days and --seed optional
uv run sonnabon
```

Open <http://localhost:8000>. When running the demonstration, building the corrected history from the generated year takes about thirty seconds on the first start. Every start after that is instant. Each page has its own address, so `#diary` and `#setup` can be linked and reloaded.

```bash
uv run sonnabon-reset       # back to a known state before a demo
uv run sonnabon-clear       # remove all data and return to an empty state
uv run sonnabon --provider ollama   # explicitly force ollama
uv run sonnabon --provider bedrock  # explicitly force bedrock
```

The agent needs a model and will say so plainly if it has none. Two ways to give
it one, either is enough:

```bash
ollama pull qwen3                 # local, no account, works
# or set AWS_REGION and credentials (and optionally AWS_BEARER_TOKEN_BEDROCK)
# in .env and enable Claude in Bedrock
```

### Running it on AWS

The AWS code is in `src/bakery/cloud/`. Each piece stays dormant on a laptop and
switches on once its AWS setting exists:

| Service | What the code does | Turned on by |
|---|---|---|
| Amazon Bedrock | The agent's model, a Strands `BedrockModel` | `--provider bedrock` and AWS credentials |
| Amazon Bedrock AgentCore Runtime | `agentcore_app.py` wraps the same agent as an AgentCore entrypoint | `agentcore configure` then `agentcore launch` |
| Amazon EventBridge Scheduler | `schedule.py` wakes the agent five minutes after closing, Tuesday to Sunday, plus a weekly review | `sonnabon-schedule --runtime-arn ... --role-arn ...` |
| Amazon S3 | `storage.py` reads the till export from a bucket and keeps a local copy current | `BILLS_FILE=s3://bucket/bills.jsonl` |
| Amazon SES | `notify_owner` sends the one email. Without SES it writes to a local outbox | `SES_FROM` and `OWNER_EMAIL` |

```bash
pip install "sonnabon[aws]"
agentcore configure --entrypoint src/bakery/cloud/agentcore_app.py
agentcore launch
sonnabon-schedule --runtime-arn <runtime ARN> --role-arn <scheduler role ARN>
```

### About Bedrock

During the hackathon neither of our AWS accounts could get Bedrock model access.
The console sent us back to a plan upgrade and registration step we could not
complete, so no Bedrock call ever reached a model. That was an account access
problem, not a code problem, and since AgentCore runs the agent on Bedrock, it
also blocked the deployment above.

The demo video therefore runs on a local model through Ollama. It is the same
Strands agent with the same eighteen tools and the same hooks; only the provider
changes, with one flag:

```bash
uv run sonnabon --provider ollama
```

There is deliberately no scripted stand-in. A templated sentence presented as
the agent's answer would make the whole product a lie, so when there is no model
it says so. Every page keeps working; only the agent needs one.

### The look

The background is a fragment shader: vertical stripes with a slow wave through
them, which is an awning rather than a pattern. Panels are glass over it.

Sonnabon itself drifts along the bottom of the page rather than sitting in a
corner. Reaching for it stops it where it is and the panel opens there, because
a button that flies home to be clicked is a button that makes you wait.

Headings are set in **Super Bakery**, free for personal and commercial use, and
its licence ships beside it in `ui/assets/` so the repo carries its own proof.
Every figure is set in the text face instead, because a display font is lovely
on a name and unreadable on a column of numbers.

## How it is built

```
src/bakery/
  core/
    analytics.py   sell-out detection, demand estimation, trends, rankings
    calendar.py    occasions, and how far ahead each has to be started
    catalogue.py   the menu, learned from the receipts themselves
    plan.py        corrected history, forecast, production quantities
    receipts.py    bills, exactly as a till prints them
  ops/
    feed.py        a trading day arriving live, one bill at a time
    journal.py     what it did and when, so the autonomy is evidence not a claim
    paths.py       one shop id, every store under it, one process per bakery
  cloud/         AgentCore entrypoint, EventBridge schedule, S3 till export
    shift.py       the shop's day, running or not
    state.py       loaded once, cached on the data file's timestamp
    team.py        whose job is what, whether it is done, who confirms sell-outs
  agent/
    agent.py       the agent, and the limits it cannot argue with
    model.py       which provider answers, and what to do when none can
    runs.py        what happens when the clock goes off
    tools.py       the eighteen things the agent can do
  simulation/
    backtest.py    would it actually have done better
    generate.py    a year of trade, sell-outs on purpose, truth kept aside
  cli.py         command-line entry points
ui/
  app.py         the demo server
  index.html     five pages, one file, no build step
```

One process serves one bakery, and that is enforced rather than hoped for:
`paths.only()` refuses a second, because the catalogue is module level and the
second shop would quietly read the first one's menu. Every store hangs off one
`SHOP_ID`, so adding a shop is a directory and two schedule entries.

The expensive step is never in a request. Building corrected history from
149,384 bills takes 24.9 seconds; reading the cache takes 0.90. So a scheduled
job builds it and everything else reads it, keyed on the receipts file's
modification time so a stale cache is impossible rather than unlikely.

Retries are safe. Each journal entry can carry a key, and it is checked before
anything is sent, so a rerun does not email twice and a task that stays overdue
is raised once rather than nightly.

**[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) has the diagram and the numbers.**

### How Strands is used

One `Agent`, built in `agent.py`, with eighteen `@tool` functions and a single
`HookProvider` attached. Nothing is orchestrated by hand: the SDK runs the loop
and the hook decides when it stops.

**The limits are hooks, not prompt text.** A ceiling written into a system
prompt is a request, and a model can talk itself out of a request. A hook that
sets `event.cancel` inside the loop is a control the model is never consulted
about. `Ledger` subscribes to three events and gates three things:

| Event | Gate |
|---|---|
| `BeforeModelCallEvent` | Cancels the next inference once the run passes its spend ceiling, or once thirty tool calls have gone by without finishing, which is looping rather than working |
| `AfterModelCallEvent` | Reads token usage from whichever shape the provider reports, so the cost is counted as the run goes rather than after it |
| `BeforeToolCallEvent` | Counts every call, and lets an irreversible action run once. The second send is the dangerous one |

The third is the one worth pausing on. Because the count comes from the tool
about to run, **"did it email the owner?" is answered by the invocation, not by
the model's closing paragraph.** An agent that says it sent something and did
not is caught, and the diary reports what actually happened rather than what was
claimed.

The provider is resolved rather than assumed. `model.py` picks Bedrock when a
region and credentials are present, a local Ollama model when one is running,
and otherwise raises with the two commands that would fix it. There is
deliberately no scripted stand-in for the agent: a templated sentence presented
as its answer would make the whole thing a lie.

**It reads summaries, samples, or code. Never the pile.** There are 149,384
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

The menu is derived, not configured. On the first read of a shop whose products
it does not recognise, it learns the whole menu from the bill lines: names and
prices come straight off them, because a till already knows both. Point it at a
different bakery's export and it works out that bakery's menu with nothing typed
in. When the products are ones it already holds it keeps what it has, because a
receipt cannot carry oven times, shelf lives or salvage values and a derived
menu would flatten them.

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
- It does not order anything. It works out the day an order is due and says so
  in time. Anything with a supplier or money on the other end stays a person's
  job, and the agent is told so in its own prompt.
- Emails go to `data/outbox.jsonl` until SES is set up.
- The artwork is a placeholder and is not committed. The font is, along with its
  licence.

## Licence

MIT.
