"""TBI demo.

Runs against local Ollama by default. Set USE_AWS=true for Bedrock.
"""

from src import memory, pipeline

SCENARIOS = [
    "Redige un email court et professionnel a notre fournisseur de tissus pour "
    "demander le numero de suivi de la commande 4088.",
    "Debug why this SQL query returns duplicate rows after I added the join.",
    "We are deciding whether to end our main supplier relationship and move "
    "production to Portugal. Walk through the risks and recommend a course.",
]


def approve(decision):
    """Human in the loop. Fires only when the router flags the request high risk."""
    print(f"\n  high risk: {decision.domain}, routing to {decision.tier}")
    return input("  authorise? (y/n): ").strip().lower() == "y"


def collect(result):
    if not result.ask_rating:
        return
    rating = input("  was this useful? (y/n): ").strip().lower()
    comment = input("  anything you would change? ").strip() if result.ask_comment else ""
    memory.rate(result.record.request_id, result.record.user,
                result.record.tier, 1 if rating == "y" else -1, comment)


def main():
    for text in SCENARIOS:
        result = pipeline.run(text, user="founder", approve=approve)
        if not result.approved:
            print("\ncase closed, owner declined")
            continue

        record = result.record
        print(f"\n[{record.tier}] {record.domain}")
        if record.ran_tier != record.tier:
            print(f"  ran on {record.ran_tier}, budget ceiling")
        print(f"  spent {record.total_cost:.6f}, decision was worth "
              f"{record.decided_cost:.6f}")
        print(f"  {result.text.strip()[:280]}")
        collect(result)

    summarise()


def summarise():
    records = memory.records()
    if not records:
        return

    spend = sum(record.total_cost for record in records)
    print(f"\n{len(records)} cases, {spend:.6f} spent")

    for user, latest, median in memory.anomalies():
        print(f"  flagged {user}: {latest:.6f} against median {median:.6f}")

    for tier, stats in memory.by_tier().items():
        print(f"  rating  {tier}: {stats['mean']:+.2f} over {stats['n']}")


if __name__ == "__main__":
    main()
