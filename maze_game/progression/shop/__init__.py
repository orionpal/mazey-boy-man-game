"""
shop/__init__.py
-----------------
The group-boundary break offers 3 perk cards drawn at random from the full
perk pool -- everything has "a chance" to show up on a given break rather
than being guaranteed every time.

Also the in-maze walk-to shop's catalog (MAZE_SHOP_ITEMS): unlike the free
group-boundary break above, this is *paid* -- gold for a perk pick (the
same ALL_PERKS pool, priced with the same
cost_base + cost_step * current_level shape progression/meta/ uses for its
permanent upgrades, just cheaper -- see SHOP_PERK_COST_BASE/STEP's
docstring in constants.py) or a flat "Time Cache" top-up. Fixed catalog,
not randomly offered like the break cards, since the shop tile itself is
already the rare/random part (spawn_shop_tile()'s chance-per-maze).
"""

import random
from dataclasses import dataclass

from maze_game.constants import (
    SHOP_TIME_PRICE, SHOP_TIME_AMOUNT, SHOP_PERK_COST_BASE, SHOP_PERK_COST_STEP, C_SHOP,
)
from maze_game.progression.entities.hazards import save_gold_total
from maze_game.progression.shop.perks import Perk, ALL_PERKS

SHOP_CARDS_OFFERED = 3


def offer_shop_cards(rng: random.Random | None = None) -> list[Perk]:
    rng = rng if rng is not None else random
    return rng.sample(ALL_PERKS, min(SHOP_CARDS_OFFERED, len(ALL_PERKS)))


# ── In-maze walk-to shop catalog ────────────────────────────────────────────


@dataclass(frozen=True)
class ShopItem:
    id: str
    name: str
    description: str
    kind: str  # "time" or "perk"
    cost_base: int
    cost_step: int = 0
    perk: Perk | None = None
    time_amount: float = 0.0


MAZE_SHOP_ITEMS: list[ShopItem] = [
    ShopItem(
        id="time_cache", name="Time Cache",
        description=f"+{SHOP_TIME_AMOUNT:.0f}s to the run clock. Repeatable.",
        kind="time", cost_base=SHOP_TIME_PRICE, time_amount=SHOP_TIME_AMOUNT,
    ),
] + [
    ShopItem(
        id=perk.id, name=perk.name, description=perk.description,
        kind="perk", cost_base=SHOP_PERK_COST_BASE, cost_step=SHOP_PERK_COST_STEP, perk=perk,
    )
    for perk in ALL_PERKS
]


def maze_shop_cost(item: ShopItem, run) -> int:
    """
    Gold cost of `item`'s *next* purchase. A perk's cost rises with how many
    times it's already been picked this run (run.build.picks), same shape
    as MetaProgress.cost_for() -- the time item has no such state, so it
    stays flat at cost_base every time.
    """
    if item.kind != "perk":
        return item.cost_base
    level = run.build.picks.get(item.perk.id, 0)
    return item.cost_base + item.cost_step * level


def purchase_maze_shop_item(run, item: ShopItem) -> bool:
    """
    Deduct gold and apply `item`'s effect, persisting the new gold total the
    same way GoldPellet.on_contact() does. Returns False (no-op) if
    unaffordable.
    """
    cost = maze_shop_cost(item, run)
    if run.gold < cost:
        return False
    run.gold -= cost
    save_gold_total(run.gold, run.gold_path)
    if item.kind == "time":
        run.time.add(item.time_amount)
        run.add_popup(run.player, f"+{item.time_amount:.0f}s", C_SHOP)
    else:
        run.build.acquire(item.perk)
        run.add_popup(run.player, f"+{item.perk.name}", C_SHOP)
    return True
