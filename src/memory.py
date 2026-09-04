"""Stores what each request cost and what the user thought of the answer.

This is the file that lets TBI improve. Routing reads it before deciding, so a
model tier the user disliked before does not get used again for the same kind
of work.

Writes to a local file by default. Set DDB_TABLE and it writes to DynamoDB
instead, with no other change. One partition per user, cases and ratings stored
together under it, so reading one user's history is a single query.

    pk  USER#<user>
    sk  CASE#<timestamp>#<request_id>   or   RATE#<request_id>
"""

import json
import os
import statistics
import time
from dataclasses import asdict, dataclass
from decimal import Decimal
from functools import lru_cache

from . import config

TABLE = os.getenv("DDB_TABLE")
LEDGER = os.getenv("LEDGER_PATH", "ledger.jsonl")
FEEDBACK = os.getenv("FEEDBACK_PATH", "feedback.jsonl")


def price(model, completion):
    return (
        completion.input_tokens * model.input_cost
        + completion.output_tokens * model.output_cost
    ) / 1_000_000


@dataclass(frozen=True)
class Record:
    request_id: str
    user: str
    domain: str
    tier: str
    ran_tier: str
    router_cost: float
    task_cost: float
    decided_cost: float
    input_tokens: int
    output_tokens: int
    at: float
    # What these same tokens would have cost on the tab the person already had
    # open. Defaulted so ledgers written before this field still load.
    baseline_cost: float = 0.0
    calls: int = 1
    # Which conversation this turn belongs to. Blank on rows written before
    # cases had turns, which is why it has a default.
    case_id: str = ""

    @property
    def total_cost(self):
        return self.router_cost + self.task_cost

    @property
    def saved(self):
        """Never negative. Routing upward is a decision, not a loss."""
        return max(self.baseline_cost - self.total_cost, 0.0)


@dataclass(frozen=True)
class Feedback:
    request_id: str
    user: str
    tier: str
    rating: int
    comment: str
    at: float


# ---------------------------------------------------------------- persistence


@lru_cache(maxsize=1)
def _table():
    import boto3

    return boto3.resource("dynamodb", region_name=config.AWS_REGION).Table(TABLE)


def _put(entry, sort_key, path):
    """DynamoDB rejects float, so numbers go through Decimal on the way in."""
    if not TABLE:
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(asdict(entry)) + "\n")
        return entry

    item = json.loads(json.dumps(asdict(entry)), parse_float=Decimal)
    item["pk"] = f"USER#{entry.user}"
    item["sk"] = sort_key
    _table().put_item(Item=item)
    return entry


def _row(cls, item):
    """Keep only fields the class still has. A ledger outlives its schema, and
    a row written last week must not crash the reader this week."""
    fields = cls.__dataclass_fields__
    return cls(**{k: float(v) if isinstance(v, Decimal) else v
                  for k, v in item.items() if k in fields})


def _rows(cls, items, prefix):
    return [
        _row(cls, item)
        for item in items
        if str(item.get("sk", "")).startswith(prefix)
    ]


def _query(prefix, cls, path, user=None):
    """Reads one user's partition when a user is given. Only a report over
    every user falls back to a scan, and that is not on the request path."""
    if not TABLE:
        try:
            with open(path, encoding="utf-8") as handle:
                rows = [_row(cls, json.loads(line)) for line in handle if line.strip()]
        except FileNotFoundError:
            return []
        return [r for r in rows if user is None or r.user == user]

    if user is None:
        return _rows(cls, _table().scan().get("Items", []), prefix)

    from boto3.dynamodb.conditions import Key

    response = _table().query(KeyConditionExpression=Key("pk").eq(f"USER#{user}"))
    return _rows(cls, response.get("Items", []), prefix)


def history(user):
    """One partition read. The whole reason for the single table layout."""
    return _query("CASE#", Record, LEDGER, user=user)


def cases(user):
    """One entry per conversation, newest first, with its turns folded in.

    The sidebar lists cases, not turns. A case that took six exchanges is one
    line with what the whole thing cost, which is the number somebody actually
    wants when they are deciding whether it was worth it.
    """
    grouped = {}
    for row in history(user):
        key = row.case_id or row.request_id
        entry = grouped.setdefault(key, {"case_id": key, "turns": 0, "cost": 0.0,
                                         "baseline": 0.0, "calls": 0, "at": row.at,
                                         "tier": row.ran_tier, "domain": row.domain,
                                         "first": row.request_id})
        entry["turns"] += 1
        entry["cost"] += row.total_cost
        entry["baseline"] += row.baseline_cost
        entry["calls"] += row.calls
        if row.at >= entry["at"]:
            entry["at"] = row.at
            entry["tier"] = row.ran_tier
            entry["domain"] = row.domain
    return sorted(grouped.values(), key=lambda e: e["at"], reverse=True)


def save(record):
    return _put(record, f"CASE#{record.at}#{record.request_id}", LEDGER)


def rate(request_id, user, tier, rating, comment=""):
    entry = Feedback(request_id, user, tier, int(rating), comment, time.time())
    return _put(entry, f"RATE#{request_id}", FEEDBACK)


def records():
    return _query("CASE#", Record, LEDGER)


def ratings(user=None):
    return _query("RATE#", Feedback, FEEDBACK, user=user)


# -------------------------------------------------------------------- queries


def build(request_id, user, decision, ran_tier, router_completion, task_completion):
    """task_cost is what we spent. decided_cost is what the routing decision
    would have cost unclamped. baseline_cost is what the same tokens would have
    cost on the model the person would otherwise have reached for, which is the
    only one of the three that is a saving rather than an accounting entry.

    Our own router tokens count against us; the baseline has no router, because
    somebody typing into an open tab does not pay for one."""
    return Record(
        request_id=request_id,
        user=user,
        domain=decision.domain,
        tier=decision.tier,
        ran_tier=ran_tier,
        router_cost=price(config.PRICED["cheap"], router_completion)
        if router_completion
        else 0.0,
        task_cost=price(config.PRICED[ran_tier], task_completion),
        decided_cost=price(config.PRICED[decision.tier], task_completion),
        baseline_cost=price(config.PRICED[config.HABIT_TIER], task_completion),
        input_tokens=task_completion.input_tokens,
        output_tokens=task_completion.output_tokens,
        at=time.time(),
    )


def build_case(request_id, user, decision, case, router_completion=None,
               case_id=""):
    """One ledger row for a whole run, summed from what the hooks saw.

    The agents' own calls are in here, and so is the classifier that chose the
    tier. Counting only the answer would flatter us by exactly the overhead the
    product exists to be honest about."""
    return Record(
        request_id=request_id,
        user=user,
        domain=decision.domain,
        tier=decision.tier,
        ran_tier=max(case.calls, key=lambda c: c.cost).tier if case.calls else decision.tier,
        router_cost=price(config.PRICED["cheap"], router_completion)
        if router_completion else 0.0,
        task_cost=case.spent,
        decided_cost=case.spent,
        baseline_cost=case.baseline,
        input_tokens=sum(c.input_tokens for c in case.calls),
        output_tokens=sum(c.output_tokens for c in case.calls),
        at=time.time(),
        calls=len(case.calls),
        case_id=case_id,
    )


RECENT = 10


def prior(user, domain):
    """What happened recently when this user asked something like this.

    Only the last RECENT rated requests count. Without a window one bad rating
    from months ago pins a domain to an expensive tier permanently, and the
    cost model inverts over time.
    """
    past = [r for r in history(user) if r.domain == domain]
    if not past:
        return None
    past.sort(key=lambda r: r.at)
    scored = {f.request_id: f.rating for f in ratings(user)}
    marks = [scored[r.request_id] for r in past if r.request_id in scored][-RECENT:]
    return {
        "n": len(past),
        "tier": statistics.mode(r.tier for r in past),
        "rating": statistics.mean(marks) if marks else None,
        "spend": sum(r.total_cost for r in past),
    }


def escalate(tier, past):
    """Raise a tier when this user has disliked answers at this level before.

    Cheap answers people rejected are not savings. The only automatic tier
    change in the system, and it only ever moves upward.
    """
    if not past or past["rating"] is None or past["rating"] >= 0:
        return tier
    index = config.TIER_ORDER.index(tier)
    return config.TIER_ORDER[min(index + 1, len(config.TIER_ORDER) - 1)]


def by_tier():
    grouped = {}
    for entry in ratings():
        grouped.setdefault(entry.tier, []).append(entry.rating)
    return {
        tier: {"mean": statistics.mean(scores), "n": len(scores)}
        for tier, scores in sorted(grouped.items())
    }


def anomalies(factor=3.0, minimum=5):
    """Users whose latest request cost a multiple of their own median."""
    by_user = {}
    for record in records():
        by_user.setdefault(record.user, []).append(record)

    flagged = []
    for user, rows in by_user.items():
        if len(rows) < minimum:
            continue
        rows.sort(key=lambda row: row.at)
        median = statistics.median(row.total_cost for row in rows[:-1])
        if median > 0 and rows[-1].total_cost > median * factor:
            flagged.append((user, rows[-1].total_cost, median))
    return flagged


def usage(user=None, days=30):
    """What the dashboard shows: where the tokens went, and what they cost.

    One pass over the window. Every figure here is a sum of provider-reported
    counts, so the dashboard cannot disagree with the ledger it came from.
    """
    cutoff = time.time() - days * 86400
    rows = [r for r in _query("CASE#", Record, LEDGER, user=user) if r.at >= cutoff]

    daily, tiers, domains = {}, {}, {}
    for row in rows:
        day = time.strftime("%Y-%m-%d", time.localtime(row.at))
        bucket = daily.setdefault(day, {"day": day, "tokens": 0, "cost": 0.0,
                                        "baseline": 0.0, "n": 0})
        bucket["tokens"] += row.input_tokens + row.output_tokens
        bucket["cost"] += row.total_cost
        bucket["baseline"] += row.baseline_cost
        bucket["n"] += 1

        for group, key in ((tiers, row.ran_tier), (domains, row.domain)):
            entry = group.setdefault(key, {"n": 0, "cost": 0.0, "tokens": 0})
            entry["n"] += 1
            entry["cost"] += row.total_cost
            entry["tokens"] += row.input_tokens + row.output_tokens

    spent = sum(r.total_cost for r in rows)
    baseline = sum(r.baseline_cost for r in rows)
    return {
        "daily": [daily[day] for day in sorted(daily)],
        "by_tier": tiers,
        "by_domain": dict(sorted(domains.items(),
                                 key=lambda kv: -kv[1]["cost"])[:8]),
        "totals": {
            "cases": len(rows),
            "calls": sum(r.calls for r in rows),
            "tokens": sum(r.input_tokens + r.output_tokens for r in rows),
            "cost": spent,
            "baseline": baseline,
            "saved": max(baseline - spent, 0.0),
            # None, not zero. Nothing measured is not the same as nothing saved.
            "saved_pct": round(100 * (1 - spent / baseline), 1)
            if baseline > 0 else None,
        },
    }
