# TBI

**Tokens Bureau of Investigation.** Your AI spending, investigated.

---

You have four AI tabs open right now.

This morning you asked one of them where a supplier order got to. You sent that
to the most expensive model you own, because that tab was already open.

Nobody decides to do that. It just happens, thirty times a day.

### The number that should bother you

> **The 7% of requests you barely notice are 38% of the bill.**

The gap between the cheapest model and the most expensive is about **143x**.

So your bill is not decided by how much you use it. It is decided by how often
you reach for the wrong thing on the few requests that are expensive.

You cannot see which ones those were. Nobody can.

---

## What TBI does

**Every request is a case, and TBI keeps the file.**

Tracking is the product. Routing is what tracking lets you fix.

| | |
|---|---|
| **Records** | every request: which model, what it cost, real tokens from the provider |
| **Asks** | now and then, whether the answer was actually any good |
| **Investigates** | flags the week your spending changed shape, and says why |
| **Routes** | to the model the work needs, because now it knows what the work is |
| **Adapts** | rewrites the ask to suit the model answering it |
| **Learns** | say no once and that kind of work moves up a tier |

After a month you have something no billing dashboard gives you.

Not what you spent. **Whether you spent it on the right things.**

---

## The bureau, and what it actually maps to

The name is not decoration. Every piece of it points at a real mechanism.

| In the bureau | In the code |
|---|---|
| a case comes in | a request arrives at one endpoint |
| the case is read before it is assigned | `scenario_agent` classifies intent, risk and domain |
| the case officer assigns it | `routing_agent` picks the tier |
| evidence is logged, not remembered | every token count comes from the provider, never estimated |
| the file stays open | `memory` keeps spend and ratings per person, per domain |
| forensics reviews the books | `forensics_agent` finds the week that does not look like the others |
| the officer needs sign off | high risk work stops and asks you, enforced in code |

The one line worth keeping from all of it: **every user has a spending pattern,
and nobody currently watches it.**

---

## One endpoint

You do not manage four accounts, four SDKs and four tabs.

```
your app  ->  TBI  ->  Nova Micro | Haiku | Sonnet | Opus
```

Same call regardless of who answers. TBI owns the choice, and because it owns
the choice it can also record it, which is the whole reason the tracking is
possible at all. A gateway you route around cannot count anything.

You keep your own keys. TBI never touches your bill, it just explains it.

---

## It rewrites the ask to fit the model

Routing down feels like a downgrade when the same words go to every tier. The
small model is not only weaker, it is being asked in a way that suits a
stronger one.

So the prompt is fitted to whoever is answering:

| Tier | What gets added |
|---|---|
| **cheap** | answer directly and stop, short sentences, no preamble, no restating the question, handle multiple parts in order |
| **mid**, **heavy** | nothing. They do not need scaffolding |
| **max** | this may be acted on and may be hard to undo. State your assumptions, and say what would change your answer |

Same request, fitted wording. It is why sending an email to Nova Micro does not
read like a downgrade, and why a decision sent to the top tier comes back with
its assumptions on the table.

---

## The team

Five agents. Four do the work, one runs the case.

```mermaid
flowchart LR
    U([person]) --> CO["case officer"]
    CO --> SA["scenario<br/>agent"]
    CO --> RA["routing<br/>agent"]
    CO --> EA["execution<br/>agent"]
    CO --> FA["forensics<br/>agent"]
    CO -.high risk.-> H{{"asks you first"}}
    RA -. reads .-> M[(memory)]
    EA -- writes --> M
    FA -. reads .-> M

    classDef agent fill:#1f2937,stroke:#60a5fa,color:#e5e7eb
    classDef store fill:#1f2937,stroke:#34d399,color:#e5e7eb
    classDef human fill:#1f2937,stroke:#fbbf24,color:#e5e7eb
    class CO,SA,RA,EA,FA agent
    class M store
    class H human
```

| Agent | Job |
|---|---|
| **scenario** | reads the request. Intent, complexity, risk, domain |
| **routing** | picks the tier, using what you thought of past answers |
| **execution** | does the work, records what it really cost |
| **forensics** | reviews your spending, speaks only when it matters |

It runs in the background and **only surfaces when there is a real decision to
make.** Full diagrams in [ARCHITECTURE.md](ARCHITECTURE.md).

---

## Show me the arithmetic

One working day for a small business owner. Every number below comes from this
table, so you can check it yourself.

Sizes are in tokens. A token is roughly three quarters of a word, so "250 in,
200 out" means a short email and a short reply.

| The work | How often<br/>per day | Size of<br/>the ask | Size of<br/>the answer | Tier | Why that tier |
|---|---:|---:|---:|---|---|
| Emails to suppliers and customers | 12 | 250 | 200 | cheap | fixed shape, no judgement |
| Social posts and product copy | 5 | 200 | 250 | cheap | short, formulaic |
| Summarising meeting notes | 3 | 1,800 | 300 | cheap | long to read, easy to do |
| Spreadsheet and formula help | 3 | 600 | 400 | mid | small mistakes are expensive |
| Code and debugging | 3 | 900 | 700 | mid | needs real reasoning |
| A supplier or pricing negotiation | 1 | 1,200 | 900 | heavy | money is on the table |
| A strategy or finance decision | 0.5 | 2,000 | 1,500 | max | you cannot take it back |

Half a day for the last row means one such decision every other day.

**27.5 tasks. 25,600 tokens.** By volume: 54% cheap, 30% mid, 8% heavy, 7% max.

That last 7% is the 38%.

Routed properly the day costs **$0.0628**, or **$1.88 a month**.

Now the same day done by hand, drifting to the habitual expensive model some of
the time:

| Drift | Per month | TBI saves |
|---:|---:|---:|
| never | $1.88 | **0%** |
| 20% | $3.42 | **45%** |
| 40% | $4.95 | **62%** |
| 60% | $6.48 | **71%** |

The top row is the floor, not a forecast. It describes somebody who routes every
request perfectly, by hand, every time, and never once reaches for the wrong tab
while thinking about something else.

**Nobody is that person. That is the entire point.**

And even for someone who is, TBI still tells them what they spent and on what,
which is the part no billing dashboard does.

---

## The models

| Tier | Model | Gets |
|---|---|---|
| cheap | `amazon.nova-micro-v1:0` | email, captions, translation, summaries |
| mid | `anthropic.claude-haiku-4-5` | code, analysis, spreadsheets, the default |
| heavy | `anthropic.claude-sonnet-5` | strategy, legal, audit, forecasting |
| max | `anthropic.claude-opus-4-8` | decisions that cannot be undone |

**Mistakes are not symmetric.** A big model on easy work wastes a fraction of a
cent. A small model on hard work gives you a confident wrong answer that you act
on, and no ledger records that.

So `cheap` has to be earned, `mid` is the fallback, and **nothing reaches the top
tier by accident.** A parse failure can never become an expensive call.

Prices live in `src/config.py` and are **Bedrock on-demand rates, checked
2026-09-02**. Two things that caught us out: Sonnet 5 ran a promotional
$2/$10 that ended 31 August 2026 and is now $3/$15, and the top tier is Opus 4.8
rather than Fable 5 because Opus is confirmed on Bedrock and Fable is not.

Model access on Bedrock is granted per model in your console. That is a gate,
not a cost, so check all four are enabled before planning around them.

---

## Run it

```bash
uv sync
```

```bash
USE_AWS=true python main.py
```

Add `DDB_TABLE=tbi` to store on DynamoDB instead of a local file. Nothing above
that line changes.

### The interface

```bash
python ui/server.py
```

Then open **localhost:8756**. It serves `ui/index.html` and runs every request
through the same `pipeline.run` the tests use, so the tier, the token counts and
the cost on screen are the real ones. There is no seeded data: an empty ledger
shows an empty bureau.

It needs a backend. Either is fine:

| | Setup | Cost |
|---|---|---|
| **Ollama** | `uv sync`, then `ollama pull qwen2.5:1.5b` and `qwen2.5:3b` | nothing |
| **Bedrock** | AWS credentials, model access enabled, then `USE_AWS=true python ui/server.py` | real |

Without one, the page says so rather than inventing numbers.

### What a $50 budget covers

A single request, roughly 800 tokens in and 600 out, on each tier:

| Tier | Model | Per request | $50 buys |
|---|---|---:|---:|
| cheap | Nova Micro | $0.000112 | ~446,000 |
| mid | Haiku 4.5 | $0.0038 | ~13,000 |
| heavy | Sonnet 5 | $0.0114 | ~4,400 |
| max | Opus 4.8 | $0.0190 | ~2,600 |

A full pass through the agent team is about six model calls, so budget roughly
**$0.01 per request** with mid tier execution, or **$0.025** if the top tier
answers. **$50 is several thousand full agent requests.**

A demo needs a few hundred. Money is not the constraint here. A runaway agent
loop is, so keep `TIER_CEILING=mid` while developing and set an AWS Budgets
alarm, which is a different thing from anything inside this repo.

These are Bedrock rates checked on 2026-09-02 against secondary sources, since
the AWS pricing page did not render its tables. Confirm in your own console.

---

## Layout

| File | Job |
|---|---|
| `src/agents.py` | **the agents.** One solo lane, and a coordinator with four specialists |
| `src/forensics.py` | the forensics agent and its four tools |
| `src/router.py` | picks a tier and reads risk. One call, keyword fallback, cached |
| `src/provider.py` | calls a model, returns what it really cost |
| `src/pipeline.py` | the one entry point. Classify, gate, pick a lane, record |
| `src/config.py` | the tier ladder and the prices |
| `src/bureau.py` | the Strands hooks: ledger, gate, budget, loop cap, sessions |
| `src/settings.py` | what the interface may change at runtime |
| `src/memory.py` | spend, ratings, latency, history, anomalies, quality |
| `ui/index.html` | the interface. One file, no build step |
| `ui/server.py` | serves it, streams each step, runs `pipeline.run` |

**No number in the ledger is estimated by a model.** Every token count comes
from the provider's own usage response, which is the only reason any figure here
is worth showing anyone.
