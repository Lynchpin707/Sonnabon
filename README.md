# TBI

Tokens Bureau of Investigation.

## The thing nobody notices

You have four AI tabs open right now.

This morning you wrote a two line email to a supplier asking where an order got
to, and you sent it to the most expensive model you own. Not because the email
needed it. Because that tab was already open.

Nobody decides to do that. It just happens, thirty times a day, and at the end
of the month there is a number you cannot really explain to yourself.

That is the problem. Not waste exactly. Drift.

## What TBI does

Every request is a case.

It gets read, classified, and sent to the model the work actually needs. What it
cost is written down, from the provider's own usage numbers, never estimated.
Now and then TBI asks whether the answer was any good. If you say no, the next
request like it goes up a tier on its own.

After a month you have something no billing dashboard gives you. Not what you
spent. Whether you spent it on the right things.

## What a day actually looks like

This is the whole argument, so here is the arithmetic in the open.

A small business owner, one working day:

| Work | Times a day | In | Out | Tier |
|---|---:|---:|---:|---|
| supplier and customer email | 12 | 250 | 200 | cheap |
| social post and product copy | 5 | 200 | 250 | cheap |
| meeting notes summary | 3 | 1800 | 300 | cheap |
| spreadsheet and formula help | 3 | 600 | 400 | mid |
| code and debugging | 3 | 900 | 700 | mid |
| supplier or pricing negotiation | 1 | 1200 | 900 | heavy |
| strategy or finance decision | 0.5 | 2000 | 1500 | max |

That is 27.5 tasks and 25,600 tokens. By volume it splits **54% cheap, 30% mid,
8% heavy, 7% max**.

Here is the part that matters. **The top tier is 7% of the tokens and 59% of the
money.** The gap between the cheapest model and the most expensive one is
roughly 285 times on input. So the bill is not decided by how much you use. It
is decided by how often you reach for the wrong thing on the few requests that
are expensive.

Routed properly, that day costs **$0.0809**, or **$2.43 a month**.

Now the same day when a real person is doing the routing by hand, and some
fraction of the time reaches for their habitual model instead:

| How often they drift to the top model | Per month | TBI saves |
|---:|---:|---:|
| never | $2.43 | 0% |
| 20% of the time | $5.76 | 58% |
| 40% of the time | $9.09 | 73% |
| 60% of the time | $12.42 | 80% |

Read the first row honestly. Against somebody with perfect routing discipline,
TBI saves nothing on cost, and that is worth saying out loud. It is also not a
real person. And that row only measures money. It says nothing about the two
minutes of deciding, the tracking, or the budget you did not blow through.

For scale, a $50 AWS budget covers about **618 full days** of this traffic.

## The models

| Tier | Model | Gets |
|---|---|---|
| cheap | `amazon.nova-micro-v1:0` | email, captions, translations, summaries |
| mid | `anthropic.claude-haiku-4-5` | code, analysis, spreadsheets, and the default |
| heavy | `anthropic.claude-sonnet-5` | strategy, legal, audit, forecasting |
| max | `anthropic.claude-fable-5` | decisions that cannot be undone |

Prices live in `src/config.py`. They are first party rates and Bedrock bills
separately, so check them against the AWS pricing page before quoting anything.

## How it decides

```
request
  |
  |-- router      one small model call: tier, domain, risk, and a cleaned prompt
  |               short prompt: keyword rules instead, no call at all
  |               bad JSON: keyword rules, request still gets served
  |               seen before: cached, no call
  |
  |-- memory      tier goes up if you disliked this kind of answer before
  |
  |-- ceiling     clamped to what the budget can actually afford to call
  |
  |-- provider    Bedrock Converse
  |
  |-- memory      written down, with real token counts
```

Two things worth knowing about the design.

**Mistakes are not symmetric.** Sending an easy task to a big model wastes a
fraction of a cent. Sending a hard one to a small model gives you a confident
wrong answer, which costs something no ledger records. So `cheap` has to be
earned, `mid` is the fallback, and nothing reaches `max` unless a model
explicitly asks for it. A parse failure can never turn into an expensive call.

**The only automatic tier change moves upward.** A cheap answer somebody
rejected was never a saving.

## Run it

```bash
uv sync
```

```bash
USE_AWS=true python main.py
```

```bash
USE_AWS=true DDB_TABLE=tbi python main.py
```

## Where it stands

Honest, because you will find out anyway.

**Written.** Routing, cost accounting, the ratings loop, spend anomaly
detection, and the budget ceiling. Not yet run against a live model.

**Written but never connected.** The DynamoDB backend. It is wired behind
DDB_TABLE and has not talked to AWS yet.

**Not started.** The dashboard, the demo video, the architecture diagram, and a
live model run.

## The agent

One, and it sits outside the request path.

`src/forensics.py` is a Strands agent that reviews a person's model spending on a
schedule. It has four tools that read the ledger, it decides for itself which to
use and when it has seen enough, and its standing instruction is to say nothing
unless something needs a decision.

Routing is not an agent. It is one classification call, and it stays a function,
because a step that always runs in the same order is not making a decision.

## Layout

| File | Job |
|---|---|
| `src/config.py` | the model ladder, prices, budget ceiling |
| `src/provider.py` | calling a model, and returning what it really cost |
| `src/router.py` | picking which model, once, per request |
| `src/memory.py` | the case file: spend, ratings, history, anomalies |
| `src/pipeline.py` | one request, start to finish. Read this first |
| `src/forensics.py` | the forensics agent. Reviews spending, speaks only when it matters |
| `src/agents.py` | the team: scenario, routing, execution, forensics, and the case officer |
| `main.py` | the demo, start here |

Nothing in the ledger is estimated by a model. Every token count comes from the
provider's own usage response, which is the only reason any number here is worth
showing anyone.
