"""Would it actually have done better?

Everything else here measures a component. This measures the product: replay the
year, and for every day compare what the shop really baked against what the
agent would have said, then price both against demand that is actually known.

Two costs, and a shop only ever sees one of them. Waste is the ingredients in
the bin, which the owner counts. Lost margin is the people who wanted something
that had run out, which nothing in the shop can count. A plan that only reduces
the first by making less is not an improvement, it is a different mistake, so
both are always reported together.

The honest caveat, stated in the output rather than buried: the corrections the
forecast learns from are built from the whole file, so a little of the future
leaks into the past. The forecast itself only ever reads days before the one it
is planning. Fixing the leak properly means rebuilding the corrections for every
day in turn, which costs hours and moves the answer very little.
"""

import json
from datetime import timedelta

from . import catalogue, plan, state


def run(days=90, from_day=None):
    """Replay the last ``days`` trading days and price both plans."""
    shop = state.get()
    truth = _truth()
    trading = [day for day in shop.days if day.isoformat() in truth]
    if from_day:
        trading = [day for day in trading if day >= from_day]
    tested = trading[-days:]

    shop_waste = shop_lost = agent_waste = agent_lost = 0.0
    rows = []

    for day in tested:
        made_truth = truth[day.isoformat()]
        agent_plan = plan.bake_plan(shop.bills, day, index=shop.index,
                                    history=shop.history)
        agent_qty = {row["item"]: row["make"] for row in agent_plan["rows"]}

        day_shop_waste = day_shop_lost = day_agent_waste = day_agent_lost = 0.0
        for name, record in made_truth.items():
            product = catalogue.get(name)
            if product.bake_minutes <= 0:
                continue                       # coffee is not a bake decision
            wanted, made = record["wanted"], record["made"]

            sold = min(wanted, made)
            day_shop_waste += (made - sold) * product.overage
            day_shop_lost += (wanted - sold) * product.margin

            planned = agent_qty.get(name)
            if planned is None:
                continue
            sold_agent = min(wanted, planned)
            day_agent_waste += (planned - sold_agent) * product.overage
            day_agent_lost += (wanted - sold_agent) * product.margin

        shop_waste += day_shop_waste
        shop_lost += day_shop_lost
        agent_waste += day_agent_waste
        agent_lost += day_agent_lost
        rows.append({
            "day": day.isoformat(),
            "shop": round(day_shop_waste + day_shop_lost, 2),
            "agent": round(day_agent_waste + day_agent_lost, 2),
        })

    shop_total, agent_total = shop_waste + shop_lost, agent_waste + agent_lost
    better = sum(1 for row in rows if row["agent"] < row["shop"])

    return {
        "days_tested": len(tested),
        "from": tested[0].isoformat() if tested else None,
        "to": tested[-1].isoformat() if tested else None,
        "currency": catalogue.CURRENCY,
        "shop": {"waste": round(shop_waste), "lost": round(shop_lost),
                 "total": round(shop_total)},
        "agent": {"waste": round(agent_waste), "lost": round(agent_lost),
                  "total": round(agent_total)},
        "saved": round(shop_total - agent_total),
        "saved_pct": round(100 * (shop_total - agent_total) / shop_total, 1)
                     if shop_total else 0,
        "better_on_days": f"{better} of {len(rows)}",
        "per_year": round((shop_total - agent_total) / max(len(tested), 1) * 306),
        "caveat": ("Sell-out corrections are learned from the whole file, so a "
                   "little future leaks into the past. Forecasts only read days "
                   "before the one they plan."),
        "rows": rows,
    }


def _truth(path="data/truth.json"):
    with open(path, encoding="utf-8") as handle:
        return {row["day"]: row["products"] for row in json.load(handle)}


if __name__ == "__main__":
    result = run(days=120)
    money = result["currency"]
    print(f"Replayed {result['days_tested']} trading days, "
          f"{result['from']} to {result['to']}")
    print()
    print(f"{'':11}{'waste':>12}{'lost sales':>13}{'total':>12}")
    for who in ("shop", "agent"):
        row = result[who]
        label = "the " + who
        print(f"{label:11}{money + format(row['waste'], ','):>12}"
              f"{money + format(row['lost'], ','):>13}"
              f"{money + format(row['total'], ','):>12}")
    print()
    print(f"saved {money}{result['saved']:,} ({result['saved_pct']}%), "
          f"better on {result['better_on_days']} days")
    print(f"annualised {money}{result['per_year']:,}")
    print()
    print(result["caveat"])
