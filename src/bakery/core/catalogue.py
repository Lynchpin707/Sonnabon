"""What the shop sells, and what it costs to make.

Two numbers decide every production call this agent makes: the margin lost when
an item runs out, and the cost of one that goes in the bin. Both come from here,
so a wrong figure here is wrong everywhere downstream and silently so.

``cost`` is the ingredient cost of one finished unit. It is the one thing the
till cannot tell you and the owner can, in a sentence: most shops know their
food cost as a percentage and can name the few items that differ.

``bake_minutes`` is optional. Nobody knows it precisely and nothing important
depends on it. It is only used if the owner volunteers an oven limit, and it is
never used to rank anything, because ranking on a number the shop cannot
actually produce is how a demo becomes a lie.

``salvage`` is what an unsold unit is still worth at close. Bread sold off at
half price is not a total loss and the maths has to know that, or it will
under-bake the one product where running out costs the most.
"""

import json
import os
from dataclasses import dataclass, asdict

# The unit every figure in this module is in. Set per shop, because this runs
# wherever there is a till, and a hard-coded symbol is a hard-coded country.
CURRENCY = os.getenv("CURRENCY", "€")


@dataclass(frozen=True)
class Product:
    name: str
    category: str
    price: float
    cost: float
    bake_minutes: float
    shelf_life_days: int
    salvage: float = 0.0
    cost_given: bool = False

    def __post_init__(self):
        if self.salvage > self.cost:
            # Day-old bread can genuinely fetch more than its ingredients
            # cost, but modelling it that way makes over-baking free, and the
            # optimum runs away to whatever the oven holds. It is not free: a
            # discounted loaf takes a sale from tomorrow's fresh one, and
            # someone still has to handle it. Keep salvage strictly below cost
            # so the trade-off stays real.
            raise ValueError(
                f"{self.name}: salvage {self.salvage} is not below cost "
                f"{self.cost}. Discount sales cannibalise fresh ones, so the "
                "recovered value has to stay under what it cost to make."
            )
        if self.price <= self.cost:
            raise ValueError(
                f"{self.name}: price {self.price} does not cover cost {self.cost}. "
                "No quantity fixes a broken price."
            )

    @property
    def margin(self):
        """What one sale earns. The cost of running out, per unit."""
        return self.price - self.cost

    @property
    def overage(self):
        """What one unsold unit costs. Not the price: the shop never had that
        money. It is what was spent making something nobody bought, less
        whatever it can still be sold or given away for."""
        return self.cost - self.salvage

    @property
    def critical_ratio(self):
        """The service level this product should actually be made to.

        Cheap staples come out high, because running out of bread costs far more
        than binning it. Expensive pastry comes out low. Owners believe the
        reverse, which is exactly why this is worth computing.
        """
        under, over = self.margin, self.overage
        if under <= 0:
            # Selling at or below cost. No quantity fixes that, and pretending
            # otherwise would hand back a confident number for a broken price.
            return 0.0
        return under / (under + over)

    @property
    def margin_per_oven_minute(self):
        """Contribution per unit of the constrained resource.

        This is the ranking nobody in a small bakery computes, and it routinely
        disagrees with both 'most units sold' and 'most revenue'. Items that are
        not baked return infinity in spirit; they are reported separately rather
        than allowed to top a ranking they do not belong in.
        """
        if self.bake_minutes <= 0:
            return None
        return self.margin / self.bake_minutes


# A working pâtisserie's board. Prices and costs are plausible European retail
# figures, not a specific shop's, and the README says so. Swap this whole list
# for a real menu and nothing downstream changes.
PRODUCTS = [
    # The everyday trade. Cheap, fast, and most of what pays the wages.
    Product("Croissant", "viennoiserie", 1.30, 0.45, 2.2, 1, salvage=0.20),
    Product("Glazed donut", "viennoiserie", 2.00, 0.60, 2.0, 1, salvage=0.25),

    # The signatures. What people cross town for, and where the margin is.
    Product("Cinnamon roll", "viennoiserie", 3.20, 1.00, 3.4, 1, salvage=0.45),
    Product("Pistachio croissant", "viennoiserie", 4.20, 1.55, 2.8, 1, salvage=0.30),

    # Desserts. Expensive, fragile, worth nothing the next morning.
    Product("Tiramisu", "patisserie", 5.20, 1.95, 4.0, 1),
    Product("Basque cheesecake", "patisserie", 5.50, 2.10, 5.0, 2, salvage=0.70),
    Product("Chocolate éclair", "patisserie", 4.20, 1.55, 4.0, 1),

    # Keeps for days, so running out barely costs anything. A useful control:
    # the agent should not be making urgent calls about cookies.
    Product("Chocolate chip cookie", "biscuit", 2.20, 0.55, 1.8, 4, salvage=0.30),

    # Not baked. Rides along with everything else and never goes to waste, which
    # is why it stays out of every waste and production ranking.
    Product("Coffee", "drink", 2.20, 0.40, 0.0, 0),
]

BY_NAME = {product.name: product for product in PRODUCTS}

# The list above is a demo board, not the truth. A real shop's menu comes from
# learn() below, derived from its own receipts, and adopt() makes it the one
# everything reads.


def unpriced():
    """Anything with no cost at all, which cannot be planned for."""
    return [product.name for product in PRODUCTS if product.cost <= 0]


def guessed_costs():
    """Costs nobody confirmed, which is what the agent should ask about first.

    ``learn()`` derives a cost for every product from a single food-cost ratio,
    because a shop that has to type in thirty costs before it sees anything
    never gets to the end of the form. The guess is good enough to plan with and
    not good enough to trust, and the difference matters: cost decides the
    service level, so a wrong one quietly biases every quantity that follows.

    Marking them keeps that honest. It is the difference between a number the
    owner told it and one it made up, and only the owner can close the gap.
    """
    return [{"item": product.name,
             "assumed_cost": round(product.cost, 2),
             "price": product.price}
            for product in PRODUCTS if not product.cost_given]


# What a discounted or staff-eaten unit recovers, as a share of what it cost to
# make. A third is deliberately conservative: the sale is real but it takes a
# customer from tomorrow's full-price one, and somebody still has to handle it.
SALVAGE_SHARE = 0.35


def learn(bills, food_cost=0.30, overrides=None, no_waste=()):
    """Build the menu from the shop's own receipts.

    Nothing here is typed in by hand. Names and prices come straight from the
    bills, because a till already knows both and asking for them again is how a
    tool becomes a form. The one thing a receipt cannot say is what an item cost
    to make, so that is derived from a single number the owner can give in a
    sentence: their food cost, usually somewhere near thirty percent.

    ``overrides`` refines individual items once the owner corrects them, and
    ``no_waste`` names anything that never goes in the bin, like coffee, so it
    stays out of every production decision.
    """
    from statistics import median

    seen = {}
    for bill in bills:
        for line in bill.lines:
            seen.setdefault(line.item, []).append(line.unit_price)

    products = []
    for name, prices in sorted(seen.items()):
        price = round(median(prices), 2)
        given = (overrides or {}).get(name, {})
        cost = given.get("cost", round(price * food_cost, 2))
        salvage = given.get("salvage", round(cost * SALVAGE_SHARE, 2))
        products.append(Product(
            name=name,
            category=given.get("category", "learned"),
            price=given.get("price", price),
            cost=cost,
            bake_minutes=given.get("bake_minutes",
                                   0.0 if name in no_waste else 1.0),
            shelf_life_days=given.get("shelf_life_days",
                                      0 if name in no_waste else 1),
            salvage=0.0 if name in no_waste else salvage,
            cost_given="cost" in given,
        ))
    return products


def adopt(products):
    """Make a learned menu the one everything else reads."""
    global PRODUCTS, BY_NAME
    PRODUCTS = list(products)
    BY_NAME = {product.name: product for product in PRODUCTS}
    return [product.name for product in PRODUCTS]


def _costs_path():
    from ..ops import paths
    return paths.of("costs")


def confirm_cost(name, cost, path=None):
    """Replace a guessed cost with one the owner actually told it.

    Cost is the one thing a receipt cannot say, and it decides the service
    level, so a guess quietly biases every quantity that follows. Confirming it
    is the whole setup conversation, and it is worth persisting: a shop should
    not answer the same question every time the server restarts.
    """
    import dataclasses
    import json
    import os

    product = get(name)
    cost = round(float(cost), 4)
    if cost <= 0:
        raise ValueError(f"{name}: a cost of {cost} is not a cost.")
    if cost >= product.price:
        raise ValueError(
            f"{name}: a cost of {cost} is not below the {product.price} it "
            f"sells for. Check whether that is the batch price rather than "
            f"the unit price.")

    updated = dataclasses.replace(
        product, cost=cost, cost_given=True,
        # Salvage was derived from the old guess, so it has to move with it or
        # it can end up above cost and make over-baking look free.
        salvage=min(product.salvage, round(cost * SALVAGE_SHARE, 4)))
    adopt([updated if p.name == name else p for p in PRODUCTS])

    target = path or _costs_path()
    try:
        known = {}
        if os.path.exists(target):
            with open(target, encoding="utf-8") as handle:
                known = json.load(handle)
        known[name] = cost
        os.makedirs(os.path.dirname(target) or ".", exist_ok=True)
        with open(target, "w", encoding="utf-8") as handle:
            json.dump(known, handle, ensure_ascii=False, indent=2)
    except OSError:
        pass                       # answered for this session, not for the next
    return updated


def load_confirmed(path=None):
    """Apply costs the owner confirmed on an earlier run."""
    import json
    import os

    target = path or _costs_path()
    if not os.path.exists(target):
        return []
    try:
        with open(target, encoding="utf-8") as handle:
            known = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return []
    applied = []
    for name, cost in known.items():
        if name in BY_NAME:
            try:
                confirm_cost(name, cost, path=target)
                applied.append(name)
            except ValueError:
                continue           # the menu changed under it; ask again
    return applied


def get(name):
    """Look a product up, loudly.

    A typo in a receipt file must not become a silent KeyError three modules
    later, or worse a zero cost that makes something look wildly profitable.
    """
    try:
        return BY_NAME[name]
    except KeyError:
        raise KeyError(
            f"{name!r} is not on the menu. Known products: "
            f"{', '.join(sorted(BY_NAME))}"
        ) from None


def baked():
    """Everything the oven actually produces. Coffee is not a production
    decision and must not appear in a bake plan."""
    return [product for product in PRODUCTS if product.bake_minutes > 0]
