"""TBI demo.

Runs the full agent team against local Ollama by default. Set USE_AWS=true for
Bedrock, or pass --fast to use the no-agent path instead.
"""

import sys

from src import agents, memory, pipeline, provider

# One per lane: a cheap solo call, a mid solo call, the full team, and one the
# bureau stops and asks about before it runs anything.
SCENARIOS = [
    "Summarise this sales call transcript into next steps and owners.",
    "Write the SQL for monthly active users by plan tier from our events table.",
    "Review the vendor contract redline and flag what I should push back on.",
    "Should we terminate the reseller agreement this quarter?",
]


def approve(decision):
    """Human in the loop. Fires before anything above the ceiling runs."""
    print(f"\n  needs your say-so: {decision.domain}, {decision.risk} risk, "
          f"wants the {decision.tier} tier")
    return input("  authorise? (y/n): ").strip().lower() == "y"


def collect(result):
    if not getattr(result, "ask_rating", False):
        return
    rating = input("  was this useful? (y/n): ").strip().lower()
    comment = input("  anything you would change? ").strip() if result.ask_comment else ""
    memory.rate(result.record.request_id, result.record.user,
                result.record.tier, 1 if rating == "y" else -1, comment)


def show(record, answer, calls=(), blocks=()):
    print(f"\n[{record.tier}] {record.domain}")
    if record.ran_tier != record.tier:
        print(f"  ran on {record.ran_tier}, budget ceiling")
    for call in calls:
        print(f"    {call.agent:<14} {call.tier:<6} "
              f"{call.input_tokens:>6} in {call.output_tokens:>5} out  "
              f"{call.cost:.6f}")
    for block in blocks:
        print(f"    STOPPED  {block.agent}: {block.reason}")
    print(f"  spent {record.total_cost:.6f}, would have cost "
          f"{record.baseline_cost:.6f} on the usual model")
    print(f"  {answer.strip()[:280]}")


def main(fast=False):
    ready, where = provider.health()
    print(f"backend: {where}")
    if not ready:
        return print("nothing to run against. Fix the line above and try again.")

    for text in SCENARIOS:
        if fast:
            result = pipeline.run(text, user="founder", approve=approve)
            if not result.approved:
                print("\ncase closed, owner declined")
                continue
            show(result.record, result.text)
            collect(result)
        else:
            case = agents.handle(text, user="founder", approve=approve)
            if not case.approved:
                print("\ncase closed, owner declined")
                continue
            show(case.record, case.answer, case.calls, case.blocks)

    summarise()


def summarise():
    records = memory.records()
    if not records:
        return

    spend = sum(record.total_cost for record in records)
    baseline = sum(record.baseline_cost for record in records)
    print(f"\n{len(records)} cases, {spend:.6f} spent, "
          f"{baseline:.6f} on the usual model")
    if baseline > 0:
        print(f"  {100 * (1 - spend / baseline):.1f}% less")

    for user, latest, median in memory.anomalies():
        print(f"  flagged {user}: {latest:.6f} against median {median:.6f}")

    for tier, stats in memory.by_tier().items():
        print(f"  rating  {tier}: {stats['mean']:+.2f} over {stats['n']}")


if __name__ == "__main__":
    main(fast="--fast" in sys.argv)
