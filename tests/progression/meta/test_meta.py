"""
Tests for maze_game.progression.meta -- MetaUpgrade/MetaProgress/Base in
isolation. Every test uses tmp_path for both gold.json and
meta_upgrades.json, so none of this ever touches the real on-disk files.
"""

import pytest

from maze_game.progression.entities.hazards import save_gold_total
from maze_game.progression.meta import (
    ALL_META_UPGRADES, MetaProgress, Base,
    load_meta_upgrade_levels, save_meta_upgrade_levels,
)


@pytest.fixture
def paths(tmp_path):
    return tmp_path / "gold.json", tmp_path / "meta_upgrades.json"


# ── ALL_META_UPGRADES ────────────────────────────────────────────────────


def test_all_meta_upgrades_have_distinct_ids_and_valid_effect_keys():
    from maze_game.progression.shop.perks import EFFECTS

    ids = [u.id for u in ALL_META_UPGRADES]
    assert len(ids) == len(set(ids))
    for upgrade in ALL_META_UPGRADES:
        assert upgrade.effect_key in EFFECTS


# ── load/save round trip ─────────────────────────────────────────────────


def test_load_meta_upgrade_levels_returns_empty_when_the_file_is_missing(tmp_path):
    assert load_meta_upgrade_levels(tmp_path / "does_not_exist.json") == {}


def test_load_meta_upgrade_levels_returns_empty_when_the_file_is_corrupt(tmp_path):
    path = tmp_path / "meta_upgrades.json"
    path.write_text("not valid json{{{")
    assert load_meta_upgrade_levels(path) == {}


def test_load_meta_upgrade_levels_skips_malformed_entries(tmp_path):
    path = tmp_path / "meta_upgrades.json"
    path.write_text('{"pellet_bonus": 2, "enemy_resistance": "not a number"}')
    assert load_meta_upgrade_levels(path) == {"pellet_bonus": 2}


def test_save_and_load_meta_upgrade_levels_round_trips(tmp_path):
    path = tmp_path / "meta_upgrades.json"
    save_meta_upgrade_levels({"pellet_bonus": 3}, path)
    assert load_meta_upgrade_levels(path) == {"pellet_bonus": 3}


# ── MetaProgress ──────────────────────────────────────────────────────────


def test_meta_progress_starts_at_zero_gold_and_no_levels_with_no_prior_save(paths):
    gold_path, upgrades_path = paths
    progress = MetaProgress(gold_path, upgrades_path)
    assert progress.gold == 0
    assert progress.levels == {}
    assert progress.level_of(ALL_META_UPGRADES[0]) == 0


def test_meta_progress_is_seeded_from_prior_saves(paths):
    gold_path, upgrades_path = paths
    save_gold_total(50, gold_path)
    save_meta_upgrade_levels({ALL_META_UPGRADES[0].id: 2}, upgrades_path)
    progress = MetaProgress(gold_path, upgrades_path)
    assert progress.gold == 50
    assert progress.level_of(ALL_META_UPGRADES[0]) == 2


def test_cost_for_rises_linearly_with_owned_level(paths):
    upgrade = ALL_META_UPGRADES[0]
    progress = MetaProgress(*paths)
    base_cost = progress.cost_for(upgrade)
    assert base_cost == upgrade.cost_base

    progress.levels[upgrade.id] = 1
    assert progress.cost_for(upgrade) == upgrade.cost_base + upgrade.cost_step

    progress.levels[upgrade.id] = 2
    assert progress.cost_for(upgrade) == upgrade.cost_base + 2 * upgrade.cost_step


def test_purchase_fails_and_is_a_no_op_when_unaffordable(paths):
    gold_path, upgrades_path = paths
    upgrade = ALL_META_UPGRADES[0]
    save_gold_total(0, gold_path)
    progress = MetaProgress(gold_path, upgrades_path)
    assert progress.can_afford(upgrade) is False
    assert progress.purchase(upgrade) is False
    assert progress.gold == 0
    assert progress.level_of(upgrade) == 0


def test_purchase_deducts_gold_levels_up_and_persists_both(paths):
    gold_path, upgrades_path = paths
    upgrade = ALL_META_UPGRADES[0]
    save_gold_total(100, gold_path)
    progress = MetaProgress(gold_path, upgrades_path)
    cost = progress.cost_for(upgrade)

    assert progress.purchase(upgrade) is True
    assert progress.gold == 100 - cost
    assert progress.level_of(upgrade) == 1

    # Persisted to disk, not just in-memory -- a fresh instance sees it too.
    reloaded = MetaProgress(gold_path, upgrades_path)
    assert reloaded.gold == 100 - cost
    assert reloaded.level_of(upgrade) == 1


def test_repeated_purchases_of_the_same_upgrade_keep_leveling_it_up(paths):
    gold_path, upgrades_path = paths
    upgrade = ALL_META_UPGRADES[0]
    save_gold_total(1000, gold_path)
    progress = MetaProgress(gold_path, upgrades_path)

    for expected_level in range(1, 4):
        assert progress.purchase(upgrade) is True
        assert progress.level_of(upgrade) == expected_level


# ── seed_build() ──────────────────────────────────────────────────────────


def test_seed_build_with_no_upgrades_owned_returns_a_plain_build(paths):
    progress = MetaProgress(*paths)
    build = progress.seed_build()
    assert build.pellet_value_multiplier == 1.0
    assert build.enemy_resistance_multiplier == 1.0


def test_seed_build_applies_owned_pellet_bonus_levels(paths):
    gold_path, upgrades_path = paths
    upgrade = next(u for u in ALL_META_UPGRADES if u.id == "pellet_bonus")
    progress = MetaProgress(gold_path, upgrades_path)
    progress.levels[upgrade.id] = 2

    build = progress.seed_build()
    assert build.pellet_value_multiplier == pytest.approx(upgrade.magnitude ** 2)


def test_seed_build_applies_owned_enemy_resistance_levels(paths):
    gold_path, upgrades_path = paths
    upgrade = next(u for u in ALL_META_UPGRADES if u.id == "enemy_resistance")
    progress = MetaProgress(gold_path, upgrades_path)
    progress.levels[upgrade.id] = 3

    build = progress.seed_build()
    assert build.enemy_resistance_multiplier == pytest.approx(upgrade.magnitude ** 3)


def test_seed_build_returns_a_fresh_build_each_call(paths):
    gold_path, upgrades_path = paths
    upgrade = ALL_META_UPGRADES[0]
    progress = MetaProgress(gold_path, upgrades_path)
    progress.levels[upgrade.id] = 1

    build_a = progress.seed_build()
    build_a.picks["x"] = 99  # mutate one instance
    build_b = progress.seed_build()
    assert build_b.picks == {}  # unaffected -- not the same object, not shared state


# ── Base cursor ───────────────────────────────────────────────────────────


def test_base_starts_at_the_first_slot():
    base = Base()
    assert base.cursor == 0
    assert base.on_start_run is False


def test_base_slot_count_is_one_more_than_the_upgrade_count():
    base = Base()
    assert base.slot_count == len(ALL_META_UPGRADES) + 1


def test_base_move_cursor_wraps_forward_and_backward():
    base = Base()
    base.move_cursor(-1)
    assert base.cursor == base.slot_count - 1  # wraps backward from 0
    base.move_cursor(1)
    assert base.cursor == 0


def test_base_on_start_run_is_true_only_on_the_final_slot():
    base = Base()
    for i in range(base.slot_count):
        base.cursor = i
        assert base.on_start_run == (i == len(ALL_META_UPGRADES))
