# Architecture

## The team

A case officer coordinates four specialists. Each specialist is its own Strands
agent with one job and one system prompt, exposed to the case officer as a tool.

```mermaid
flowchart TD
    U([person]) --> CO

    CO["case officer<br/><i>decides who to call</i>"]

    CO --> SA["scenario agent<br/><i>intent, complexity,<br/>risk, domain</i>"]
    SA --> CO
    CO --> RA["routing agent<br/><i>picks the tier</i>"]
    RA --> CO
    CO -.high risk.-> H{{"ask the owner"}}
    H -.approved.-> CO
    CO --> EA["execution agent<br/><i>does the work,<br/>records the cost</i>"]
    EA --> CO
    CO --> FA["forensics agent<br/><i>reviews spending,<br/>speaks only if it matters</i>"]
    FA --> CO

    CO --> ANS([answer])

    RA -. reads history .-> M[(memory)]
    EA -- writes record --> M
    FA -. reads ledger .-> M
    EA --> P[/"provider<br/>Bedrock Converse"/]

    classDef agent fill:#1f2937,stroke:#60a5fa,color:#e5e7eb
    classDef store fill:#1f2937,stroke:#34d399,color:#e5e7eb
    classDef human fill:#1f2937,stroke:#fbbf24,color:#e5e7eb
    class CO,SA,RA,EA,FA agent
    class M,P store
    class H human
```

The forensics agent is the only one that runs outside a request, on a schedule,
so it never adds delay to anything a person is waiting for.

## Choosing a tier

Four tiers, and the decision is deliberately biased upward. Sending easy work to
a big model wastes a fraction of a cent. Sending hard work to a small model
produces a confident wrong answer that somebody acts on, and no ledger records
that cost.

```mermaid
flowchart LR
    R([request]) --> S{under 400<br/>characters?}
    S -- yes --> K["keyword rules<br/><i>no model call</i>"]
    S -- no --> C{seen this<br/>before?}
    C -- yes --> H["cached decision<br/><i>no model call</i>"]
    C -- no --> M["routing agent"]
    M -- unreadable reply --> K
    K --> E{disliked at this<br/>tier before?}
    H --> E
    M --> E
    E -- yes --> UP["move up one tier"]
    E -- no --> T
    UP --> T[tier]
    T --> CE["clamp to budget ceiling"]
    CE --> X([execute])

    classDef free fill:#1f2937,stroke:#34d399,color:#e5e7eb
    class K,H free
```

Two safety properties fall out of this. The keyword fallback never escalates to
the top tier, so a parse failure can never turn into an expensive call. And the
only automatic tier change moves upward, because a cheap answer somebody
rejected was never a saving.

## Storage

One interface, two backends, selected by whether `DDB_TABLE` is set. Nothing
above this line knows which one is in use.

```mermaid
flowchart TD
    A["memory.save()<br/>memory.rate()<br/>memory.history()"] --> Q{DDB_TABLE set?}
    Q -- no --> J["JSONL files<br/><i>local development</i>"]
    Q -- yes --> D[("DynamoDB<br/>single table")]

    D --- N["pk  USER#user<br/>sk  CASE#time#id<br/>sk  RATE#id"]

    classDef store fill:#1f2937,stroke:#34d399,color:#e5e7eb
    class J,D store
```

One partition per user, cases and ratings stored together underneath it, so
reading a person's whole history is a single query rather than a scan.

## Where the money is counted

Tokens enter the system through exactly one door. If a number is wrong, it is
wrong in one of these four functions and nowhere else.

```mermaid
flowchart LR
    P["provider.complete()<br/><i>reads usage from the<br/>provider response</i>"] --> B["memory.price()<br/><i>tokens to dollars</i>"]
    B --> C["memory.build()<br/><i>what ran, what it cost,<br/>what the decision was worth</i>"]
    C --> S["memory.save()"]
```

No number in the ledger is estimated by a model.

## One entry point, two lanes

`pipeline.run` is the only way in. It classifies the request, applies the
approval rule, picks a lane, and records the result.

| Lane | What runs | When |
|---|---|---|
| solo | one Strands agent, no tools | formulaic work, most traffic |
| team | a coordinator with four specialists as tools | judgement work, or high risk |

Both lanes are Strands agents wired to the same hooks, so the ledger, the
approval gate, the spend budget and the loop cap apply identically. The lane
only decides how many heads look at the problem, never whether the controls
run.

An earlier version had a second, agent-free path for speed. It was faster
because it was doing less than anyone believed, and nothing it did was
recorded the same way.

## Local and deployed

One switch, `USE_AWS`. Off, every agent runs on Ollama and costs nothing. On,
every agent runs on Bedrock. The tiers, the ledger, the gate and the prices
used for accounting do not move; only the model behind each tier does.

Locally the coordinator is the only agent that calls tools, and small models
are unreliable at that, so `OLLAMA_MID` is the setting worth raising if the
team lane misbehaves.
