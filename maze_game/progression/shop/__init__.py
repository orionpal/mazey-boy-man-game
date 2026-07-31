"""
shop/__init__.py
-----------------
The group-boundary break offers 3 perk cards drawn at random from the full
perk pool -- everything has "a chance" to show up on a given break rather
than being guaranteed every time.
"""

import random

from maze_game.progression.shop.perks import Perk, ALL_PERKS

SHOP_CARDS_OFFERED = 3


def offer_shop_cards(rng: random.Random | None = None) -> list[Perk]:
    rng = rng if rng is not None else random
    return rng.sample(ALL_PERKS, min(SHOP_CARDS_OFFERED, len(ALL_PERKS)))
