"""
shop/__init__.py
-----------------
The group-boundary break offers 3 cards drawn at random from the combined
pool of passive perks and active items -- everything has "a chance" to show
up on a given break rather than perks being guaranteed every time.
"""

import random

from maze_game.progression.shop.perks import Perk, ALL_PERKS
from maze_game.progression.shop.items import Item, ALL_ITEMS

SHOP_CARDS_OFFERED = 3


def offer_shop_cards(rng: random.Random | None = None) -> list[Perk | Item]:
    rng = rng if rng is not None else random
    pool = ALL_PERKS + ALL_ITEMS
    return rng.sample(pool, min(SHOP_CARDS_OFFERED, len(pool)))
