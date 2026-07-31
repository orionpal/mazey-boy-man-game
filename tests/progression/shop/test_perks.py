"""
Tests for maze_game.progression.shop.perks -- Perk/Build in isolation, no
LabyrinthRun needed.
"""

import pytest

from maze_game.progression.shop.perks import Perk, Build, ALL_PERKS


def test_build_starts_with_no_picks_and_unit_multipliers():
    build = Build()
    assert build.picks == {}
    assert build.pellet_frequency_multiplier == 1.0
    assert build.pellet_value_multiplier == 1.0
    assert build.enemy_resistance_multiplier == 1.0


def test_acquiring_a_perk_records_the_pick_and_applies_its_effect():
    build = Build()
    perk = Perk(id="x", name="X", description="d", effect_key="pellet_value", magnitude=1.5)
    build.acquire(perk)
    assert build.picks == {"x": 1}
    assert build.pellet_value_multiplier == pytest.approx(1.5)


def test_acquiring_the_same_perk_twice_stacks_multiplicatively():
    build = Build()
    perk = Perk(id="x", name="X", description="d", effect_key="pellet_frequency", magnitude=2.0)
    build.acquire(perk)
    build.acquire(perk)
    assert build.picks == {"x": 2}
    assert build.pellet_frequency_multiplier == pytest.approx(4.0)  # 2.0 * 2.0, compounding


def test_acquiring_an_enemy_resistance_effect_reduces_the_multiplier():
    build = Build()
    perk = Perk(id="x", name="X", description="d", effect_key="enemy_resistance", magnitude=0.9)
    build.acquire(perk)
    build.acquire(perk)
    assert build.enemy_resistance_multiplier == pytest.approx(0.81)  # 0.9 * 0.9, compounding down


def test_all_perks_have_distinct_ids_and_valid_effect_keys():
    ids = [p.id for p in ALL_PERKS]
    assert len(ids) == len(set(ids))
    build = Build()
    for perk in ALL_PERKS:
        build.acquire(perk)  # must not raise KeyError for any effect_key
