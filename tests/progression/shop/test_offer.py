"""
Tests for maze_game.progression.shop::offer_shop_cards -- the random draw of
shop cards, in isolation.
"""

import random

from maze_game.progression.shop import offer_shop_cards, SHOP_CARDS_OFFERED
from maze_game.progression.shop.perks import ALL_PERKS


def test_offer_shop_cards_draws_from_the_perk_pool():
    random.seed(1)
    cards = offer_shop_cards()
    assert len(cards) == min(SHOP_CARDS_OFFERED, len(ALL_PERKS))
    assert all(card in ALL_PERKS for card in cards)


def test_offer_shop_cards_with_explicit_rng_is_deterministic():
    a = offer_shop_cards(rng=random.Random(21))
    b = offer_shop_cards(rng=random.Random(21))
    assert a == b


def test_offer_shop_cards_with_explicit_rng_does_not_perturb_global_random_state():
    random.seed(555)
    state_before = random.getstate()
    offer_shop_cards(rng=random.Random(1))
    assert random.getstate() == state_before
