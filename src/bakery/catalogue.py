"""What the shop sells, and what it costs to make.

Two numbers decide every production call this agent makes: the margin lost when
an item runs out, and the cost of one that goes in the bin. Both come from here,
so a wrong figure here is wrong everywhere downstream and silently so.

``cost`` is the ingredient cost of one finished unit, not the price of a sack of
flour. ``bake_minutes`` is oven occupancy for one unit's share of a tray, which
is what makes the oven a constraint rather than a detail: a product that holds
the oven twice as long has to earn twice as much to deserve the slot.

``salvage`` is what an unsold unit is still worth at close. Bread sold off at
half price is not a total loss and the maths has to know that, or it will
under-bake the one product where running out costs the most.
"""

import json
from dataclasses import dataclass, asdict

# The unit every figure in this module is in. Changed in one place so a demo can
# be re-denominated without hunting through the analytics.
CURRENCY = "€"


@dataclass(frozen=True)
class Product:
    name: str
    category: str
    price: float
    cost: float
    bake_minutes: float
    shelf_life_days: int
    salvage: float = 0.0

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
    def perishable(self):
        return self.shelf_life_days <= 1 and self.bake_minutes > 0

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
    # Bread. Cheap, high volume, and the thing customers walk out over.
    Product("Baguette", "bread", 1.20, 0.30, 2.0, 1, salvage=0.18),
    Product("Pain de campagne", "bread", 3.40, 0.85, 5.5, 2, salvage=0.50),
    Product("Sourdough loaf", "bread", 4.20, 1.05, 6.0, 2, salvage=0.60),

    # Viennoiserie. The morning trade.
    Product("Croissant", "viennoiserie", 1.30, 0.45, 2.2, 1, salvage=0.20),
    Product("Pain au chocolat", "viennoiserie", 1.50, 0.55, 2.2, 1, salvage=0.25),
    Product("Chausson aux pommes", "viennoiserie", 1.80, 0.62, 2.6, 1, salvage=0.30),
    Product("Cinnamon roll", "viennoiserie", 2.80, 0.90, 3.4, 1, salvage=0.40),
    Product("Escargot pistache", "viennoiserie", 2.60, 0.95, 2.8, 1, salvage=0.35),

    # Pâtisserie. The afternoon, and most of the margin.
    Product("Éclair chocolat", "patisserie", 4.20, 1.55, 4.0, 1),
    Product("Mille-feuille", "patisserie", 4.80, 1.80, 4.5, 1),
    Product("Tarte au citron", "patisserie", 4.50, 1.60, 4.5, 2, salvage=0.80),
    Product("Paris-Brest", "patisserie", 5.20, 2.00, 4.5, 1),
    Product("Flan pâtissier", "patisserie", 3.60, 1.10, 6.5, 2, salvage=0.70),
    Product("Chou crème brûlée", "patisserie", 4.60, 1.70, 4.0, 1),

    # Keeps for days, so the newsvendor barely applies. Useful as a control:
    # the agent should not be making urgent calls about biscuits.
    Product("Cookie", "biscuit", 2.20, 0.55, 1.8, 4, salvage=0.30),
    Product("Madeleines x4", "biscuit", 3.20, 0.85, 1.6, 5, salvage=0.45),

    # Not baked. Rides along with everything else and never goes to waste, which
    # is why it must be excluded from any waste or oven ranking.
    Product("Café", "drink", 1.80, 0.35, 0.0, 0),
]

BY_NAME = {product.name: product for product in PRODUCTS}

# Where the shop the agent is actually working for lives. The list above is a
# demo board, not the truth: the truth is whatever the onboarding interview
# established and wrote here. Everything downstream reads through BY_NAME, so
# loading a real shop swaps the whole menu without touching another module.
SHOP_FILE = "shop.json"


def load_shop(path=SHOP_FILE):
    """Replace the board with a real one.

    Called after onboarding. Returns what was loaded so the caller can say so:
    quietly swapping a shop's entire cost base and not mentioning it is how a
    demo ends up reporting somebody else's margins.
    """
    global PRODUCTS, BY_NAME
    with open(path, encoding="utf-8") as handle:
        records = json.load(handle)

    products = [Product(**record) for record in records]
    missing = [p.name for p in products if p.cost <= 0]
    if missing:
        # A zero cost makes an item look infinitely profitable and puts it top
        # of every ranking. Refuse rather than flatter.
        raise ValueError(
            "These products have no cost, so their margins would be fiction: "
            + ", ".join(missing)
        )

    PRODUCTS = products
    BY_NAME = {product.name: product for product in PRODUCTS}
    return [product.name for product in PRODUCTS]


def save_shop(products, path=SHOP_FILE):
    """Persist what the interview learned, so it is asked once and not again."""
    with open(path, "w", encoding="utf-8") as handle:
        json.dump([asdict(product) for product in products], handle,
                  ensure_ascii=False, indent=2)
    return path


def unpriced():
    """Products the agent still has to ask about.

    The onboarding interview is driven off this: anything whose cost or bake
    time is unknown is a question worth a human's time, and everything else is
    not. Asking about what can be inferred is how an assistant becomes a form.
    """
    return [product.name for product in PRODUCTS
            if product.cost <= 0 or (product.category != "drink"
                                     and product.bake_minutes <= 0)]


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
