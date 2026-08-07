"""
Tests for maze_game.progression.run -- dimension ramp, the persistent
TimeResource, the LabyrinthRun state machine (sequencing, shop-choice
breaks, timeout failure, restart), and pellet/hazard contact via move().
Perk/Build is tested in isolation under tests/progression/shop/.
"""

import time

import pytest

from maze_game.constants import (
    MIN_DIMENSION, MAX_DIMENSION, DIMENSION_STEP,
    MILESTONE_INTERVAL, MILESTONE_DIMENSION_BOOST, MILESTONE_MAX_DIMENSION,
    LABYRINTH_GROUP_SIZE, LABYRINTH_TOTAL_MAZES, LABYRINTH_START_TIME,
    HAZARD_TIME_PENALTY, SPEED_BONUS_TIME, POPUP_DURATION_SECONDS,
    ROTATE_INTERVAL_BASE_SECONDS, SECOND_WIND_REFILL_SECONDS,
    TWIN_GOAL_CLUSTER_SIZE,
)
from maze_game.progression.run import (
    dimensions_for_maze, is_milestone_maze, TimeResource, LabyrinthRun,
    TeleportAnimation, RotationTimer, PauseMenu, PAUSE_OPTIONS,
)
from maze_game.progression.entities.hazards import Pellet, GoldPellet, Hazard, load_gold_total
from maze_game.progression.shop.perks import ALL_PERKS, Perk
from maze_game.progression.augments.gating.teleporters import TeleportersAugment
from maze_game.progression.augments.gating.doors import DoorKeyPair, Key, DoorsAugment
from maze_game.progression.augments.runtime.rotation import RotatingMazeAugment, rotate_cell_cw
from maze_game.progression.augments.runtime.fog import FogOfWarAugment, visible_cells_from
from maze_game.progression.augments.shifting_room import ShiftingRoomAugment, PressurePad
from maze_game.progression.augments.twin_goals import TwinGoalsAugment

# A trivial straight 3-cell corridor, (1,1)-(2,1)-(3,1), used to drive
# move() deterministically instead of a randomly-generated maze.
CORRIDOR_GRID = [
    [1, 1, 1, 1, 1],
    [1, 0, 0, 0, 1],
    [1, 1, 1, 1, 1],
]


@pytest.fixture(autouse=True)
def _isolate_gold_file(tmp_path, monkeypatch):
    """
    Every LabyrinthRun() in this file (there are dozens, unlike Game's
    single history_path-taking fixture) should never touch the real
    on-disk gold.json/meta_upgrades.json -- patching the module-level
    defaults the __init__ falls back to isolates all of them at once.
    """
    monkeypatch.setattr("maze_game.progression.run.DEFAULT_GOLD_PATH", tmp_path / "gold.json")
    monkeypatch.setattr("maze_game.progression.run.DEFAULT_META_UPGRADES_PATH", tmp_path / "meta_upgrades.json")


# ── dimensions_for_maze ───────────────────────────────────────────────────


def test_dimensions_start_at_min_dimension():
    assert dimensions_for_maze(1) == (MIN_DIMENSION, MIN_DIMENSION)
    assert dimensions_for_maze(LABYRINTH_GROUP_SIZE) == (MIN_DIMENSION, MIN_DIMENSION)


def test_dimensions_step_up_after_each_group():
    first_of_group_2 = LABYRINTH_GROUP_SIZE + 1
    assert dimensions_for_maze(first_of_group_2) == (
        MIN_DIMENSION + DIMENSION_STEP,
        MIN_DIMENSION + DIMENSION_STEP,
    )


def test_dimensions_are_monotonically_nondecreasing_apart_from_milestone_reverts():
    """
    Non-decreasing everywhere except the single-maze drop right after a
    milestone spike (e.g. maze 30 spikes, maze 31 reverts to the normal
    ramp) -- a deliberate one-off, not a bug.
    """
    prev = dimensions_for_maze(1)
    for i in range(2, LABYRINTH_TOTAL_MAZES + 1):
        cur = dimensions_for_maze(i)
        if not is_milestone_maze(i - 1):
            assert cur[0] >= prev[0] and cur[1] >= prev[1]
        prev = cur


def test_dimensions_cap_at_max_dimension_on_non_milestone_mazes():
    non_milestone_final = LABYRINTH_TOTAL_MAZES - 1  # 99 -- not a MILESTONE_INTERVAL multiple, not the final maze
    assert not is_milestone_maze(non_milestone_final)
    assert dimensions_for_maze(non_milestone_final) == (MAX_DIMENSION, MAX_DIMENSION)


# ── Milestone mazes: a one-off dimension spike ────────────────────────────


def test_is_milestone_maze_true_on_the_interval_and_the_final_maze():
    assert is_milestone_maze(MILESTONE_INTERVAL) is True
    assert is_milestone_maze(MILESTONE_INTERVAL * 2) is True
    assert is_milestone_maze(LABYRINTH_TOTAL_MAZES) is True
    assert is_milestone_maze(MILESTONE_INTERVAL - 1) is False
    assert is_milestone_maze(MILESTONE_INTERVAL + 1) is False


def test_a_milestone_maze_is_bigger_than_the_normal_ramp_would_give_it():
    normal_group_index = (MILESTONE_INTERVAL - 1) // LABYRINTH_GROUP_SIZE
    normal_size = min(MIN_DIMENSION + normal_group_index * DIMENSION_STEP, MAX_DIMENSION)
    spiked_size, _ = dimensions_for_maze(MILESTONE_INTERVAL)
    assert spiked_size > normal_size
    assert spiked_size == min(normal_size + MILESTONE_DIMENSION_BOOST, MILESTONE_MAX_DIMENSION)


def test_the_maze_right_after_a_milestone_reverts_to_the_normal_ramp():
    reverted, _ = dimensions_for_maze(MILESTONE_INTERVAL + 1)
    assert not is_milestone_maze(MILESTONE_INTERVAL + 1)
    assert reverted < dimensions_for_maze(MILESTONE_INTERVAL)[0]


def test_milestone_spike_never_exceeds_milestone_max_dimension():
    for maze_index in range(1, LABYRINTH_TOTAL_MAZES + 1):
        if is_milestone_maze(maze_index):
            size, _ = dimensions_for_maze(maze_index)
            assert size <= MILESTONE_MAX_DIMENSION


def test_final_maze_dimensions_match_the_milestone_formula():
    group_index = (LABYRINTH_TOTAL_MAZES - 1) // LABYRINTH_GROUP_SIZE
    normal_size = min(MIN_DIMENSION + group_index * DIMENSION_STEP, MAX_DIMENSION)
    expected = min(normal_size + MILESTONE_DIMENSION_BOOST, MILESTONE_MAX_DIMENSION)
    assert dimensions_for_maze(LABYRINTH_TOTAL_MAZES) == (expected, expected)


def test_milestone_maze_has_a_real_goal_and_spawns_normally():
    run = LabyrinthRun()
    run.maze_index = MILESTONE_INTERVAL
    run._begin_maze()
    assert run.goal is not None
    assert (run.cols, run.rows) == dimensions_for_maze(MILESTONE_INTERVAL)
    # A maze this size comfortably clears every density formula's minimum.
    assert len(run.pellets) > 0


# ── TimeResource ──────────────────────────────────────────────────────────


def test_time_resource_ticks_down_by_real_elapsed_time():
    resource = TimeResource(10.0)
    resource._last_tick -= 0.05  # simulate 0.05s having passed
    resource.tick()
    assert resource.amount == pytest.approx(9.95, abs=0.02)


def test_time_resource_tick_returns_the_elapsed_seconds():
    resource = TimeResource(10.0)
    resource._last_tick -= 0.05  # simulate 0.05s having passed
    elapsed = resource.tick()
    assert elapsed == pytest.approx(0.05, abs=0.02)


def test_time_resource_add_and_spend():
    resource = TimeResource(10.0)
    resource.add(5.0)
    assert resource.amount == 15.0
    resource.spend(3.0)
    assert resource.amount == 12.0


def test_time_resource_spend_clamps_at_zero():
    resource = TimeResource(2.0)
    resource.spend(100.0)
    assert resource.amount == 0.0
    assert resource.depleted is True


def test_time_resource_not_depleted_above_zero():
    resource = TimeResource(0.01)
    assert resource.depleted is False


def test_time_resource_scale_halves_the_amount():
    resource = TimeResource(10.0)
    resource.scale(0.5)
    assert resource.amount == pytest.approx(5.0)


def test_time_resource_scale_clamps_at_zero():
    resource = TimeResource(10.0)
    resource.scale(-1.0)
    assert resource.amount == 0.0


# ── LabyrinthRun lifecycle ────────────────────────────────────────────────


@pytest.fixture
def run():
    return LabyrinthRun()


def test_starts_at_maze_1_with_min_dimensions_and_full_time(run):
    assert run.maze_index == 1
    assert (run.cols, run.rows) == (MIN_DIMENSION, MIN_DIMENSION)
    assert run.on_break is False
    assert run.failed is False
    assert run.completed_run is False
    assert run.finished is False
    assert run.time.amount == pytest.approx(LABYRINTH_START_TIME)
    assert run.build.picks == {}


def test_shield_charges_start_at_zero_with_no_bulwark_picked(run):
    assert run.shield_charges_remaining == 0


def test_shield_charges_refill_to_the_build_amount_on_a_new_maze():
    run = LabyrinthRun()
    bulwark = next(p for p in ALL_PERKS if p.effect_key == "hazard_shield")
    run.build.acquire(bulwark)
    run.build.acquire(bulwark)
    run.shield_charges_remaining = 0  # simulate having spent both charges
    run.player = run.goal
    run.update()  # advances to the next maze, refilling the charge count
    assert run.shield_charges_remaining == 2


def test_update_ticks_the_time_resource(run):
    before = run.time.amount
    time.sleep(0.05)
    run.update()
    assert run.time.amount < before


# ── Momentum / Compound Interest / Second Wind perks ─────────────────────


def test_momentum_bonus_applies_on_a_hazard_free_clear():
    run = LabyrinthRun()
    momentum = next(p for p in ALL_PERKS if p.effect_key == "momentum")
    run.build.acquire(momentum)
    before = run.build.pellet_value_multiplier
    run.hazard_contacts_this_maze = 0
    run.player = run.goal
    run.update()
    assert run.build.pellet_value_multiplier == pytest.approx(before + run.build.momentum_bonus_per_clear)
    assert "momentum_bonus" in run.events


def test_momentum_bonus_does_not_apply_after_a_hazard_contact():
    run = LabyrinthRun()
    momentum = next(p for p in ALL_PERKS if p.effect_key == "momentum")
    run.build.acquire(momentum)
    before = run.build.pellet_value_multiplier
    run.hazard_contacts_this_maze = 1
    run.player = run.goal
    run.update()
    assert run.build.pellet_value_multiplier == pytest.approx(before)
    assert "momentum_bonus" not in run.events


def test_momentum_bonus_does_not_apply_without_the_perk():
    run = LabyrinthRun()
    before = run.build.pellet_value_multiplier
    run.hazard_contacts_this_maze = 0
    run.player = run.goal
    run.update()
    assert run.build.pellet_value_multiplier == pytest.approx(before)
    assert "momentum_bonus" not in run.events


def test_compound_interest_adds_time_proportional_to_gold_and_elapsed_time():
    run = LabyrinthRun()
    compound_interest = next(p for p in ALL_PERKS if p.effect_key == "compound_interest")
    run.build.acquire(compound_interest)
    run.gold = 100
    run.time._last_tick -= 1.0  # simulate exactly 1s having passed
    before = run.time.amount
    run.update()
    # The normal tick-down subtracts the same ~1s of elapsed time first --
    # compound interest is on top of that, not instead of it.
    expected_gain = run.gold * run.build.compound_interest_rate * 1.0
    assert run.time.amount == pytest.approx(before - 1.0 + expected_gain, abs=0.05)


def test_compound_interest_adds_nothing_without_the_perk():
    run = LabyrinthRun()
    run.gold = 100
    run.time._last_tick -= 1.0
    before = run.time.amount
    run.update()
    assert run.time.amount == pytest.approx(before - 1.0, abs=0.05)  # only the normal tick-down, no trickle


def test_second_wind_refills_instead_of_failing_on_depletion():
    run = LabyrinthRun()
    second_wind = next(p for p in ALL_PERKS if p.effect_key == "second_wind")
    run.build.acquire(second_wind)
    run.time.amount = 0.0
    run.update()
    assert run.failed is False
    assert run.time.amount == pytest.approx(SECOND_WIND_REFILL_SECONDS, abs=0.05)
    assert run.build.second_wind_charges == 0  # consumed
    assert "second_wind" in run.events


def test_second_wind_only_saves_once_per_charge():
    run = LabyrinthRun()
    second_wind = next(p for p in ALL_PERKS if p.effect_key == "second_wind")
    run.build.acquire(second_wind)
    run.time.amount = 0.0
    run.update()  # consumes the only charge, refills
    run.time.amount = 0.0
    run.update()  # no charges left -- fails normally
    assert run.failed is True
    assert "fail" in run.events


def test_second_wind_charges_reset_by_restart():
    run = LabyrinthRun()
    second_wind = next(p for p in ALL_PERKS if p.effect_key == "second_wind")
    run.build.acquire(second_wind)
    run.restart()
    assert run.build.second_wind_charges == 0  # Build is reseeded fresh, no owned meta upgrade grants this


def test_pellets_and_hazards_never_spawn_on_start_or_goal(run):
    assert run.player not in [p.pos for p in run.pellets]
    assert run.goal not in [p.pos for p in run.pellets]
    assert run.player not in [e.pos for e in run.hazards]
    assert run.goal not in [e.pos for e in run.hazards]
    assert run.player not in [g.pos for g in run.gold_pellets]
    assert run.goal not in [g.pos for g in run.gold_pellets]


def test_gold_pellets_never_overlap_pellets():
    """Regardless of which spawns first, a gold pellet must never land on the same cell as a time pellet."""
    for seed in range(20):
        run = LabyrinthRun(seed=seed)
        pellet_positions = {p.pos for p in run.pellets}
        gold_positions = {g.pos for g in run.gold_pellets}
        assert pellet_positions.isdisjoint(gold_positions)


def test_hazards_are_empty_before_the_unlock_maze(run):
    assert run.hazards == []


def test_completing_a_non_group_boundary_maze_advances_seamlessly(run):
    assert run.maze_index % LABYRINTH_GROUP_SIZE != 0
    run.player = run.goal
    run.update()
    assert run.maze_index == 2
    assert run.on_break is False
    assert run.finished is False  # finished is per-maze; the new maze isn't finished


def test_completing_the_last_maze_of_a_group_offers_shop_choices():
    """
    Shop choices are a random draw of 3 from the full perk pool (confirmed:
    this replaces the old guaranteed-all-3-perks behavior), so this only
    checks length and pool membership, not exact identity.
    """
    run = LabyrinthRun()
    for _ in range(LABYRINTH_GROUP_SIZE):
        assert run.on_break is False
        run.player = run.goal
        run.update()
    assert run.on_break is True
    assert run.maze_index == LABYRINTH_GROUP_SIZE  # doesn't advance until choose_shop_card()
    assert len(run.shop_choices) == min(3, len(ALL_PERKS))
    assert all(card in ALL_PERKS for card in run.shop_choices)


def test_choose_shop_card_applies_the_card_and_advances_past_the_break():
    run = LabyrinthRun()
    for _ in range(LABYRINTH_GROUP_SIZE):
        run.player = run.goal
        run.update()
    assert run.on_break is True

    chosen = run.shop_choices[0]
    run.choose_shop_card(0)
    assert run.on_break is False
    assert run.shop_choices is None
    assert "card_select" in run.events
    assert run.maze_index == LABYRINTH_GROUP_SIZE + 1
    assert (run.cols, run.rows) == (MIN_DIMENSION + DIMENSION_STEP, MIN_DIMENSION + DIMENSION_STEP)
    assert run.build.picks == {chosen.id: 1}


def test_choose_shop_card_is_a_no_op_when_not_on_break(run):
    assert run.on_break is False
    run.choose_shop_card(0)
    assert run.maze_index == 1
    assert run.build.picks == {}


def test_break_cursor_starts_at_zero_and_wraps_with_move_break_cursor():
    run = LabyrinthRun()
    for _ in range(LABYRINTH_GROUP_SIZE):
        run.player = run.goal
        run.update()
    assert run.on_break is True
    assert run.break_cursor == 0

    run.move_break_cursor(-1)
    assert run.break_cursor == len(run.shop_choices) - 1  # wraps backward
    run.move_break_cursor(1)
    assert run.break_cursor == 0
    run.move_break_cursor(1)
    assert run.break_cursor == 1


def test_move_break_cursor_is_a_no_op_when_not_on_break(run):
    assert run.on_break is False
    run.move_break_cursor(1)
    assert run.break_cursor == 0


def test_choosing_a_perk_does_not_retroactively_charge_the_break_duration():
    """
    Regression test: update() correctly skips TimeResource.tick() while
    on_break, but without TimeResource.resync() in choose_shop_card(), the tick
    reference point goes stale for the whole break -- so the very next
    tick() after resuming would compute its delta against a timestamp from
    before the break started, charging the entire break duration in one
    lump the instant play resumes (looks like "the timer didn't stop for
    the perk screen", just deferred by one frame).
    """
    run = LabyrinthRun()
    for _ in range(LABYRINTH_GROUP_SIZE):
        run.player = run.goal
        run.update()
    assert run.on_break is True

    time_at_break_start = run.time.amount
    run.time._last_tick -= 30.0  # simulate 30s spent choosing a perk
    run.choose_shop_card(0)
    assert run.time.amount == pytest.approx(time_at_break_start)  # resync alone changes nothing yet

    run.update()  # the first frame after resuming
    assert run.time.amount == pytest.approx(time_at_break_start, abs=0.05)


def test_running_out_of_time_fails_the_run(run):
    run.time.amount = 0.0
    run.update()
    assert run.failed is True


def test_move_is_a_no_op_once_failed(run):
    run.time.amount = 0.0
    run.update()
    pos_before = run.player
    run.move((1, 0))
    assert run.player == pos_before


def test_move_is_a_no_op_while_on_break():
    run = LabyrinthRun()
    for _ in range(LABYRINTH_GROUP_SIZE):
        run.player = run.goal
        run.update()
    assert run.on_break is True
    pos_before = run.player
    run.move((1, 0))
    assert run.player == pos_before


def test_restart_resets_time_and_build():
    run = LabyrinthRun()
    for _ in range(LABYRINTH_GROUP_SIZE):
        run.player = run.goal
        run.update()
    run.choose_shop_card(0)
    run.time.amount = 0.0
    run.update()
    assert run.failed is True

    run.restart()
    assert run.maze_index == 1
    assert run.failed is False
    assert run.on_break is False
    assert run.completed_run is False
    assert (run.cols, run.rows) == (MIN_DIMENSION, MIN_DIMENSION)
    assert run.time.amount == pytest.approx(LABYRINTH_START_TIME)
    assert run.build.picks == {}


# ── Gold (persistent across restart, unlike time) ─────────────────────────


def test_gold_starts_at_zero_with_no_prior_save(tmp_path):
    run = LabyrinthRun(gold_path=tmp_path / "gold.json")
    assert run.gold == 0


def test_gold_is_seeded_from_a_prior_save_on_construction(tmp_path):
    from maze_game.progression.entities.hazards import save_gold_total

    path = tmp_path / "gold.json"
    save_gold_total(17, path)
    run = LabyrinthRun(gold_path=path)
    assert run.gold == 17


def test_restart_does_not_reset_gold():
    run = LabyrinthRun()
    run.gold = 5
    run.restart()
    assert run.gold == 5


def test_owned_meta_upgrades_seed_the_starting_build(tmp_path):
    from maze_game.progression.meta import ALL_META_UPGRADES, save_meta_upgrade_levels

    upgrade = next(u for u in ALL_META_UPGRADES if u.id == "pellet_bonus")
    upgrades_path = tmp_path / "meta_upgrades.json"
    save_meta_upgrade_levels({upgrade.id: 2}, upgrades_path)

    run = LabyrinthRun(gold_path=tmp_path / "gold.json", meta_upgrades_path=upgrades_path)
    assert run.build.pellet_value_multiplier == pytest.approx(upgrade.magnitude ** 2)


def test_restart_reseeds_the_build_from_the_same_owned_meta_upgrades(tmp_path):
    from maze_game.progression.meta import ALL_META_UPGRADES, save_meta_upgrade_levels

    upgrade = next(u for u in ALL_META_UPGRADES if u.id == "hazard_resistance")
    upgrades_path = tmp_path / "meta_upgrades.json"
    save_meta_upgrade_levels({upgrade.id: 1}, upgrades_path)

    run = LabyrinthRun(gold_path=tmp_path / "gold.json", meta_upgrades_path=upgrades_path)
    run.build.acquire(ALL_PERKS[0])  # in-run pick, should reset
    run.restart()
    assert run.build.hazard_resistance_multiplier == pytest.approx(upgrade.magnitude)  # meta upgrade persists
    assert run.build.picks == {}  # in-run pick did not


def test_completing_the_final_maze_sets_completed_run_not_on_break():
    run = LabyrinthRun()
    for maze_num in range(1, LABYRINTH_TOTAL_MAZES + 1):
        run.player = run.goal
        run.update()
        while run.on_break and maze_num != LABYRINTH_TOTAL_MAZES:
            run.choose_break_card(0)  # may need to clear more than one stacked break (e.g. shop then augment)
    assert run.completed_run is True
    assert run.on_break is False
    assert run.maze_index == LABYRINTH_TOTAL_MAZES


# ── New pacing: power-up / modifier cadence ───────────────────────────────


def test_maze_5_completion_shows_shop_break_only():
    """5 is a group boundary but not an AUGMENT_INTERVAL(10) multiple -- shop only, no augment break."""
    run = LabyrinthRun()
    run.maze_index = 5
    run._advance()
    assert run.break_kind == "shop"
    run.choose_break_card(0)
    assert run.on_break is False
    assert run.maze_index == 6


def test_maze_10_completion_stacks_shop_then_augment():
    """
    10 is a multiple of both LABYRINTH_GROUP_SIZE(5) and AUGMENT_INTERVAL(10)
    -- both breaks fire, shop first, augment second (order asserted by
    _breaks_due_after), not one replacing the other.
    """
    run = LabyrinthRun()
    run.maze_index = 10
    run._advance()
    assert run.break_kind == "shop"
    run.choose_break_card(0)
    assert run.events == ["card_select"]
    assert run.break_kind == "augment"
    assert run.augment_choices is not None
    run.choose_break_card(0)
    assert run.events == ["card_select", "card_select"]
    assert run.on_break is False
    assert run.maze_index == 11


def test_maze_30_completion_stacks_shop_then_augment_before_maze_31():
    """30 is a multiple of both 5 and 10 -- stacks the same shop-then-augment breaks as any other double-boundary maze."""
    run = LabyrinthRun()
    run.maze_index = 30
    run._advance()
    assert run.break_kind == "shop"
    run.choose_break_card(0)
    assert run.break_kind == "augment"
    run.choose_break_card(0)
    assert run.on_break is False
    assert run.maze_index == 31


def test_stacked_breaks_do_not_retroactively_charge_the_combined_break_duration():
    """
    Mirrors test_choosing_a_perk_does_not_retroactively_charge_the_break_duration,
    but for two *stacked* breaks (maze 10: shop then augment) -- the clock
    must not be resynced (and therefore not charged) between the two, only
    once after the whole queue drains, or the same TimeResource staleness
    bug docs/progression.md documents once would resurface for the combined
    case specifically.
    """
    run = LabyrinthRun()
    run.maze_index = 10
    run._advance()
    assert run.break_kind == "shop"

    time_at_break_start = run.time.amount
    run.time._last_tick -= 15.0  # simulate 15s spent on the shop screen
    run.choose_break_card(0)
    assert run.break_kind == "augment"
    assert run.time.amount == pytest.approx(time_at_break_start)  # not resynced yet -- queue isn't drained

    run.time._last_tick -= 15.0  # simulate another 15s spent on the modifier screen
    run.choose_break_card(0)
    assert run.on_break is False
    assert run.time.amount == pytest.approx(time_at_break_start)  # resync alone changes nothing yet

    run.update()  # first frame after both breaks resolve
    assert run.time.amount == pytest.approx(time_at_break_start, abs=0.05)  # neither stretch was charged


def test_repeated_augment_breaks_level_up_a_single_active_augment(monkeypatch):
    """
    With only one augment registered, every modifier break necessarily
    offers a single forced card -- expected graceful degradation, not a
    bug (mirrors ALL_AUGMENTS' real length before Doors & Keys shipped as
    a second augment). Driving all 9 augment breaks in a run (mazes
    10..90) should just keep leveling that one augment up. Monkeypatched
    down to one augment rather than asserting on the current real count,
    so this keeps testing "repeated picks compose" regardless of how many
    augments actually exist.
    """
    monkeypatch.setattr("maze_game.progression.augments.ALL_AUGMENTS", [TeleportersAugment()])
    run = LabyrinthRun()
    for boundary in range(10, 100, 10):
        run.maze_index = boundary
        run._advance()
        assert run.break_kind == "shop"
        run.choose_break_card(0)
        assert run.break_kind == "augment"
        assert len(run.augment_choices) == 1
        run.choose_break_card(0)
        assert run.on_break is False
    assert run.augment_build.level_of("teleporters") == 9


# ── Seeded runs ───────────────────────────────────────────────────────────


def test_explicit_seed_is_stored_verbatim():
    run = LabyrinthRun(seed=12345)
    assert run.seed == 12345


def test_no_seed_still_assigns_some_int_seed():
    run = LabyrinthRun()
    assert isinstance(run.seed, int)


def _scripted_playthrough(run, moves):
    """Drive a run through group/augment breaks, always picking card 0, until `moves` mazes have cleared."""
    for _ in range(moves):
        run.player = run.goal
        run.update()
        while run.on_break:
            run.choose_break_card(0)  # may need to clear more than one stacked break (e.g. shop then augment)


def test_same_seed_produces_identical_maze_and_entities():
    a = LabyrinthRun(seed=999)
    b = LabyrinthRun(seed=999)
    assert a.grid == b.grid
    assert [p.pos for p in a.pellets] == [p.pos for p in b.pellets]
    assert [e.pos for e in a.hazards] == [e.pos for e in b.hazards]
    assert a.goal == b.goal


def test_same_seed_stays_identical_across_a_scripted_playthrough():
    a = LabyrinthRun(seed=42)
    b = LabyrinthRun(seed=42)
    _scripted_playthrough(a, LABYRINTH_GROUP_SIZE * 2)
    _scripted_playthrough(b, LABYRINTH_GROUP_SIZE * 2)
    assert a.grid == b.grid
    assert a.maze_index == b.maze_index
    assert [p.pos for p in a.pellets] == [p.pos for p in b.pellets]


def test_restart_without_same_seed_picks_a_new_seed():
    run = LabyrinthRun(seed=7)
    run.restart()
    assert run.seed != 7


def test_restart_with_same_seed_keeps_the_seed_and_reproduces_the_next_maze():
    run = LabyrinthRun(seed=7)
    grid_before = run.grid
    run.restart(same_seed=True)
    assert run.seed == 7
    assert run.grid == grid_before


def test_group_number_and_total_groups(run):
    assert run.group_number == 1
    assert run.total_groups == LABYRINTH_TOTAL_MAZES // LABYRINTH_GROUP_SIZE

    for _ in range(LABYRINTH_GROUP_SIZE):
        run.player = run.goal
        run.update()
    run.choose_shop_card(0)
    assert run.group_number == 2


# ── Speed bonus ───────────────────────────────────────────────────────────


def test_completing_a_maze_quickly_awards_a_speed_bonus(run):
    before = run.time.amount
    run.player = run.goal
    run.update()  # completed a fraction of a second after _begin_maze() -- well under par
    assert run.time.amount == pytest.approx(before + SPEED_BONUS_TIME, abs=0.05)


def test_completing_a_maze_quickly_adds_a_speed_bonus_popup(run):
    goal = run.goal
    run.player = goal
    run.update()
    assert any(p.text == f"+{SPEED_BONUS_TIME:.1f}s" and p.pos == goal for p in run.popups)


def test_completing_a_maze_quickly_appends_speed_bonus_and_maze_complete_events(run):
    run.player = run.goal
    run.update()
    assert run.events == ["speed_bonus", "maze_complete"]


def test_completing_a_maze_quickly_with_gold_rush_awards_bonus_gold(tmp_path):
    gold_rush = next(p for p in ALL_PERKS if p.effect_key == "gold_rush")
    run = LabyrinthRun(gold_path=tmp_path / "gold.json")
    run.build.acquire(gold_rush)
    run.build.acquire(gold_rush)
    before_gold = run.gold
    goal = run.goal
    run.player = goal
    run.update()
    assert run.gold == before_gold + 2
    assert load_gold_total(run.gold_path) == run.gold  # persisted immediately, like GoldPellet.on_contact()
    assert run.events == ["speed_bonus", "gold", "maze_complete"]
    assert any(p.text == "+2g" and p.pos == goal for p in run.popups)


def test_completing_a_maze_quickly_without_gold_rush_does_not_touch_gold(run):
    before_gold = run.gold
    run.player = run.goal
    run.update()
    assert run.gold == before_gold
    assert "gold" not in run.events


def test_completing_a_maze_slowly_does_not_award_a_speed_bonus(run):
    run._maze_started_at -= (run._par_seconds + 5.0)
    before = run.time.amount
    run.player = run.goal
    run.update()
    assert run.time.amount <= before  # no bonus, only the tiny real-time tick


def test_completing_a_maze_slowly_appends_only_the_maze_complete_event(run):
    run._maze_started_at -= (run._par_seconds + 5.0)
    run.player = run.goal
    run.update()
    assert run.events == ["maze_complete"]


# ── move() contact resolution ────────────────────────────────────────────


def _corridor_run() -> LabyrinthRun:
    run = LabyrinthRun()
    run.grid = [row[:] for row in CORRIDOR_GRID]
    run.player = (1, 1)
    run.goal = (3, 1)
    run.pellets = []
    run.gold_pellets = []
    run.hazards = []
    return run


def test_move_collects_a_pellet_along_the_slide_path():
    run = _corridor_run()
    run.pellets = [Pellet((2, 1), value=4.0)]
    before = run.time.amount
    run.move((1, 0))
    assert run.player == (3, 1)
    assert run.pellets == []
    assert run.time.amount == pytest.approx(before + 4.0 * run.build.pellet_value_multiplier)


def test_move_collects_a_gold_pellet_along_the_slide_path():
    run = _corridor_run()
    run.gold_pellets = [GoldPellet((2, 1), value=3)]
    run.move((1, 0))
    assert run.player == (3, 1)
    assert run.gold_pellets == []
    assert run.gold == 3
    assert run.events == ["move", "gold"]


def test_move_collecting_a_pellet_adds_a_popup_at_its_position():
    run = _corridor_run()
    run.pellets = [Pellet((2, 1), value=4.0)]
    run.move((1, 0))
    assert len(run.popups) == 1
    assert run.popups[0].pos == (2, 1)
    assert run.popups[0].text == f"+{4.0 * run.build.pellet_value_multiplier:.1f}s"


def test_move_takes_hazard_damage_along_the_slide_path_and_hazard_persists():
    run = _corridor_run()
    hazard = Hazard((2, 1))
    run.hazards = [hazard]
    before = run.time.amount
    run.move((1, 0))
    assert run.time.amount == pytest.approx(max(0.0, before - HAZARD_TIME_PENALTY))
    assert run.hazards == [hazard]  # persistent hazard, not consumed


def test_move_hitting_an_hazard_adds_a_popup_at_its_position():
    run = _corridor_run()
    run.hazards = [Hazard((2, 1))]
    run.move((1, 0))
    assert len(run.popups) == 1
    assert run.popups[0].pos == (2, 1)
    assert run.popups[0].text == f"-{HAZARD_TIME_PENALTY:.1f}s"


# ── Sound events (run.events) ────────────────────────────────────────────


def test_move_appends_the_move_event():
    run = _corridor_run()
    run.move((1, 0))
    assert run.events == ["move"]


def test_move_collecting_a_pellet_appends_move_and_pellet_events():
    run = _corridor_run()
    run.pellets = [Pellet((2, 1), value=4.0)]
    run.move((1, 0))
    assert run.events == ["move", "pellet"]


def test_move_hitting_an_hazard_appends_move_and_hazard_hit_events():
    run = _corridor_run()
    run.hazards = [Hazard((2, 1))]
    run.move((1, 0))
    assert run.events == ["move", "hazard_hit"]


def test_move_that_does_not_move_the_player_appends_no_event():
    run = _corridor_run()
    run.move((0, 1))  # into a wall from (1, 1) in CORRIDOR_GRID
    assert run.player == (1, 1)
    assert run.events == []


TELEPORT_GRID = [
    [1, 1, 1, 1, 1],
    [1, 0, 0, 0, 1],
    [1, 1, 1, 1, 1],
]


def _teleport_run() -> LabyrinthRun:
    run = LabyrinthRun()
    run.grid = [row[:] for row in TELEPORT_GRID]
    run.player = (1, 1)
    run.goal = (3, 1)
    run.pellets = []
    run.gold_pellets = []
    run.hazards = []
    run._teleport_map = {(2, 1): (3, 1)}
    return run


def test_moving_through_a_teleporter_appends_the_teleport_event_not_move():
    run = _teleport_run()
    run.move((1, 0))
    assert run.player == (3, 1)
    assert run.events == ["teleport"]


def test_moving_through_a_teleporter_starts_a_teleport_animation():
    run = _teleport_run()
    run.move((1, 0))
    assert run.teleport_animation is not None
    assert run.teleport_animation.from_cell == (2, 1)  # the teleporter's entrance
    assert run.teleport_animation.to_cell == (3, 1)  # its exit, == run.player


def test_an_ordinary_move_does_not_start_a_teleport_animation():
    run = _corridor_run()
    run.move((1, 0))
    assert run.teleport_animation is None


def test_teleport_animation_expires_after_its_duration():
    from maze_game.constants import ZIP_ANIMATION_DURATION_SECONDS

    run = _teleport_run()
    run.move((1, 0))
    assert run.teleport_animation is not None
    run.teleport_animation.started_at -= ZIP_ANIMATION_DURATION_SECONDS + 0.1  # simulate time passing
    run.update()
    assert run.teleport_animation is None




DOOR_GRID = [
    [1, 1, 1, 1, 1],
    [1, 0, 0, 0, 1],
    [1, 1, 1, 1, 1],
]


def _door_run() -> LabyrinthRun:
    run = LabyrinthRun()
    run.grid = [row[:] for row in DOOR_GRID]
    run.player = (1, 1)
    run.goal = (3, 1)
    run.pellets = []
    run.gold_pellets = []
    run.hazards = []
    pair = DoorKeyPair(door=(3, 1), key=(2, 1), mandatory=True, color_index=0)
    run.doors = [pair]
    run._locked_doors = {(3, 1)}
    run.keys = [Key((2, 1), door_cell=(3, 1))]
    return run


def test_moving_onto_a_key_unlocks_its_door_and_appends_the_key_event():
    run = _door_run()
    run.move((1, 0))
    assert run.player == (2, 1)  # stopped one cell short of the still-locked door
    assert run.events == ["move", "key"]
    assert run.keys == []
    assert (3, 1) not in run._locked_doors


def test_moving_through_a_door_before_its_key_is_collected_stops_short():
    run = _door_run()
    run.player = (2, 1)  # skip straight to the door's doorstep, key not yet collected
    run.move((1, 0))
    assert run.player == (2, 1)  # locked door blocks the slide, same as a wall
    assert run.events == []


def test_door_stays_unlocked_for_the_rest_of_the_maze_once_its_key_is_collected():
    run = _door_run()
    run.move((1, 0))  # collects the key, unlocking the door
    run.move((1, 0))  # now passes straight through
    assert run.player == (3, 1)


def test_restart_clears_events():
    run = _corridor_run()
    run.move((1, 0))
    assert run.events != []
    run.restart()
    assert run.events == []


# ── Rotating maze augment ────────────────────────────────────────────────


def _rotating_run(seed: int = 1) -> LabyrinthRun:
    run = LabyrinthRun(seed=seed)
    run.augment_build.acquire(RotatingMazeAugment())
    run._begin_maze()
    return run


def test_rotation_timer_ticks_down_by_real_elapsed_time():
    timer = RotationTimer(10.0)
    timer._last_tick -= 0.05  # simulate 0.05s having passed
    timer.tick()
    assert timer.remaining == pytest.approx(9.95, abs=0.02)


def test_update_rotates_the_maze_once_the_timer_expires():
    run = _rotating_run()
    before_grid = [row[:] for row in run.grid]
    run.rotation_timer.remaining = -0.01  # force expiry on the next tick
    run.update()
    assert run.grid != before_grid
    # Timer reset to (roughly) a fresh interval, not left at/below zero.
    assert run.rotation_timer.remaining > 0


def test_update_does_not_rotate_when_the_augment_is_inactive():
    run = LabyrinthRun(seed=1)
    run._begin_maze()
    before_grid = [row[:] for row in run.grid]
    run.rotation_timer.remaining = -100.0  # would clearly have fired if active
    run.update()
    assert run.grid == before_grid


def test_update_does_not_tick_the_rotation_timer_while_on_break():
    run = _rotating_run()
    run.break_kind = "shop"  # force on_break without going through the real flow
    run.rotation_timer.remaining = 1.0
    run.rotation_timer._last_tick -= 30.0  # simulate 30s having passed
    run.update()
    assert run.rotation_timer.remaining == 1.0  # untouched -- update() gates on on_break before ticking anything


def test_resuming_after_a_break_does_not_retroactively_rotate():
    """
    Regression test for the same staleness bug class TimeResource.resync()
    already fixed once (see test_choosing_a_perk_does_not_retroactively_charge_the_break_duration):
    without RotationTimer.resync() in _resume_after_break(), the timer's
    tick reference point goes stale for the whole break, so the very next
    tick() after resuming would compute a huge elapsed delta and fire a
    rotation (or several) the instant play resumes.
    """
    run = _rotating_run()
    for _ in range(LABYRINTH_GROUP_SIZE):
        run.player = run.goal
        run.update()
    assert run.on_break is True

    run.rotation_timer.remaining = 1.5
    run.rotation_timer._last_tick -= 30.0  # simulate 30s spent on the break screen
    run.choose_shop_card(0)
    assert run.rotation_timer.remaining == 1.5  # resync alone changes nothing yet

    before_grid = [row[:] for row in run.grid]
    run.update()  # the first frame after resuming
    assert run.rotation_timer.remaining == pytest.approx(1.5, abs=0.05)
    assert run.grid == before_grid  # no runaway rotation triggered by the stale gap


def test_rotate_maze_transforms_every_entity_family_consistently():
    run = LabyrinthRun(seed=7)
    run.augment_build.acquire(TeleportersAugment())
    run.augment_build.acquire(DoorsAugment())
    run.augment_build.acquire(RotatingMazeAugment())
    run._begin_maze()
    assert run.teleporters and run.doors  # otherwise this test proves nothing

    n = run.cols
    before_player = run.player
    before_goal = run.goal
    before_teleporters = list(run.teleporters)
    before_doors = list(run.doors)
    before_locked = set(run._locked_doors)

    run._rotate_maze()

    assert run.player == rotate_cell_cw(before_player, n)
    assert run.goal == rotate_cell_cw(before_goal, n)
    assert [p.a for p in run.teleporters] == [rotate_cell_cw(p.a, n) for p in before_teleporters]
    assert [p.b for p in run.teleporters] == [rotate_cell_cw(p.b, n) for p in before_teleporters]
    assert [d.door for d in run.doors] == [rotate_cell_cw(d.door, n) for d in before_doors]
    assert [d.key for d in run.doors] == [rotate_cell_cw(d.key, n) for d in before_doors]
    assert run._locked_doors == {rotate_cell_cw(c, n) for c in before_locked}
    # _teleport_map rebuilt consistently with the rotated teleporters list.
    for pair in run.teleporters:
        assert run._teleport_map[pair.a] == pair.b
        assert run._teleport_map[pair.b] == pair.a


def test_rotate_maze_is_the_identity_after_four_rotations():
    run = _rotating_run(seed=3)
    before_grid = [row[:] for row in run.grid]
    before_player = run.player
    for _ in range(4):
        run._rotate_maze()
    assert run.grid == before_grid
    assert run.player == before_player


def test_rotate_maze_clears_any_in_flight_teleport_animation():
    run = _rotating_run()
    run.teleport_animation = TeleportAnimation(run.player, run.player, time.monotonic())
    run._rotate_maze()
    assert run.teleport_animation is None


def test_rotation_warning_active_flips_true_within_the_lead_time():
    from maze_game.constants import ROTATE_WARNING_LEAD_SECONDS

    run = _rotating_run()
    run.rotation_timer.remaining = ROTATE_WARNING_LEAD_SECONDS + 1.0
    assert run.rotation_warning_active is False
    run.rotation_timer.remaining = ROTATE_WARNING_LEAD_SECONDS - 0.1
    assert run.rotation_warning_active is True


def test_rotation_warning_active_is_always_false_when_the_augment_is_inactive():
    run = LabyrinthRun(seed=1)
    run._begin_maze()
    run.rotation_timer.remaining = 0.0  # would be well within the warning window if active
    assert run.rotation_warning_active is False


def test_restart_resets_the_rotation_timer():
    run = _rotating_run()
    run.rotation_timer.remaining = -5.0
    run.restart()
    assert run.rotation_timer.remaining == pytest.approx(ROTATE_INTERVAL_BASE_SECONDS, abs=0.05)


# ── Fog of war augment ───────────────────────────────────────────────────


def _fog_run(seed: int = 1) -> LabyrinthRun:
    run = LabyrinthRun(seed=seed)
    run.augment_build.acquire(FogOfWarAugment())
    run._begin_maze()
    return run


def test_begin_maze_seeds_discovered_cells_with_the_starting_view():
    run = _fog_run()
    assert run.discovered_cells == visible_cells_from(run.grid, run.player)
    assert run.discovered_cells  # non-empty -- START_POS always sees at least itself


def test_discovered_cells_stays_empty_when_the_augment_is_inactive():
    run = LabyrinthRun(seed=1)
    run._begin_maze()
    assert run.discovered_cells == set()


def test_moving_accumulates_newly_visible_cells_into_discovered_cells():
    run = _fog_run()
    before = set(run.discovered_cells)
    run.move((1, 0))
    assert run.discovered_cells >= before  # never shrinks
    assert run.discovered_cells == before | visible_cells_from(run.grid, run.player)


def test_discovered_cells_never_shrinks_moving_back_and_forth():
    """Permanent-memory default: once seen, a cell stays in discovered_cells even after moving away from it."""
    run = _fog_run()
    run.move((1, 0))
    peak = set(run.discovered_cells)
    run.move((-1, 0))
    assert run.discovered_cells >= peak


def test_visible_and_discovered_cells_returns_none_when_fog_is_inactive():
    run = LabyrinthRun(seed=1)
    run._begin_maze()
    assert run.visible_and_discovered_cells() is None


def test_visible_and_discovered_cells_returns_the_accumulator_when_active():
    run = _fog_run()
    assert run.visible_and_discovered_cells() is run.discovered_cells


def test_begin_maze_resets_discovered_cells_for_a_new_maze():
    run = _fog_run()
    run.move((1, 0))
    assert run.discovered_cells
    run._begin_maze()
    assert run.discovered_cells == visible_cells_from(run.grid, run.player)


def test_rotate_maze_rotates_discovered_cells_in_lockstep():
    run = LabyrinthRun(seed=5)
    run.augment_build.acquire(FogOfWarAugment())
    run.augment_build.acquire(RotatingMazeAugment())
    run._begin_maze()
    run.move((1, 0))
    n = run.cols
    before = set(run.discovered_cells)
    run._rotate_maze()
    assert run.discovered_cells == {rotate_cell_cw(c, n) for c in before}


# ── Shifting room augment ────────────────────────────────────────────────
# A corridor (1,1)-(2,1)-(3,1)-(4,1)-(5,1) with a pad at (3,1) controlling a
# wall segment at (5,2) -- initially closed, sealing off the pocket cell
# (5,3) -- so move() can drive the real pass-through/one-shot trigger
# semantics deterministically instead of via a randomly-generated maze.

PRESSURE_PAD_GRID = [
    [1, 1, 1, 1, 1, 1, 1],
    [1, 0, 0, 0, 0, 0, 1],
    [1, 1, 1, 1, 1, 1, 1],
    [1, 1, 1, 1, 1, 0, 1],
    [1, 1, 1, 1, 1, 1, 1],
]


def _pressure_pad_run() -> LabyrinthRun:
    run = LabyrinthRun()
    run.grid = [row[:] for row in PRESSURE_PAD_GRID]
    run.player = (1, 1)
    run.goal = (5, 3)
    run.pellets = []
    run.gold_pellets = []
    run.hazards = []
    pad = PressurePad(pad=(3, 1), wall_segment=(5, 2), mandatory=True, color_index=0)
    run.pressure_pads = [pad]
    run._pad_by_cell = {pad.pad: pad.wall_segment}
    return run


def test_sliding_over_a_pressure_pad_triggers_it_even_without_stopping():
    """The one behavior the user was most explicit about: passing OVER a pad triggers it, even though the slide never stops there."""
    run = _pressure_pad_run()
    assert run.grid[2][5] == 1  # wall_segment still closed
    run.move((1, 0))  # slides straight through (3, 1) to the dead end at (5, 1) -- never stops on the pad itself
    assert run.player == (5, 1)
    assert run.grid[2][5] == 0  # opened despite never stopping there
    assert run.events == ["pressure_pad", "move"]
    assert len(run.popups) == 1
    assert run.popups[0].text == "shift!"


def test_pressure_pad_is_one_shot():
    run = _pressure_pad_run()
    run.move((1, 0))  # triggers it, ends at (5, 1)
    run.events = []
    run.popups = []
    run.move((-1, 0))  # slide back left, passing over the pad again
    assert run.grid[2][5] == 0  # still open
    assert run.events == ["move"]  # no second "pressure_pad" event/popup
    assert run.popups == []


def test_begin_maze_extracts_pressure_pads_and_builds_pad_lookup():
    found = False
    for seed in range(10):
        run = LabyrinthRun(seed=seed)
        run.augment_build.acquire(ShiftingRoomAugment())
        run._begin_maze()
        if run.pressure_pads:
            found = True
            for pad in run.pressure_pads:
                assert run._pad_by_cell[pad.pad] == pad.wall_segment
    assert found, "no seed placed any pad -- test is vacuous"


def test_begin_maze_does_not_crash_when_the_goal_is_inside_a_sealed_pocket():
    """
    Regression test: shortest_path() used to raise KeyError computing
    _par_seconds whenever ctx.goal landed inside a still-sealed
    pressure-pad pocket -- a genuinely closed wall, unlike a locked door
    (which stays grid-open). _begin_maze() must plan against every pad
    pre-opened instead of the literal, still-sealed self.grid.
    """
    for seed in range(30):
        run = LabyrinthRun(seed=seed)
        run.augment_build.acquire(ShiftingRoomAugment())
        run._begin_maze()  # must not raise
        assert run._par_seconds >= 0


def test_rotate_maze_rotates_pressure_pads_and_preserves_triggered_state():
    run = LabyrinthRun(seed=7)
    run.augment_build.acquire(ShiftingRoomAugment())
    run.augment_build.acquire(RotatingMazeAugment())
    run._begin_maze()
    assert run.pressure_pads  # otherwise this test proves nothing

    n = run.cols
    pad = run.pressure_pads[0]
    run._trigger_pressure_pad(*pad.pad)  # trigger it before rotating
    assert run.grid[pad.wall_segment[1]][pad.wall_segment[0]] == 0

    before_pads = list(run.pressure_pads)
    run._rotate_maze()

    assert [p.pad for p in run.pressure_pads] == [rotate_cell_cw(p.pad, n) for p in before_pads]
    assert [p.wall_segment for p in run.pressure_pads] == [rotate_cell_cw(p.wall_segment, n) for p in before_pads]
    rotated_wall = rotate_cell_cw(pad.wall_segment, n)
    assert run.grid[rotated_wall[1]][rotated_wall[0]] == 0  # triggered state carried through via self.grid itself
    assert run._pad_by_cell[rotate_cell_cw(pad.pad, n)] == rotated_wall


# ── Twin Goals augment ────────────────────────────────────────────────────


def _twin_goals_run(seed: int = 1) -> LabyrinthRun:
    """maze_index bumped to ~21x21 -- the 9x9 starting size is too small for the default distance-fraction thresholds to reliably find a candidate."""
    run = LabyrinthRun(seed=seed)
    run.augment_build.acquire(TwinGoalsAugment())
    run.maze_index = 31
    run._begin_maze()
    return run


def test_secondary_goal_is_set_when_twin_goals_is_active():
    run = _twin_goals_run()
    assert run.secondary_goal is not None
    assert run.secondary_goal != run.goal
    assert run.secondary_goal != run.player


def test_secondary_goal_stays_none_when_the_augment_is_inactive():
    run = LabyrinthRun(seed=1)
    run.maze_index = 31
    run._begin_maze()
    assert run.secondary_goal is None


def test_maze_cleared_via_the_secondary_goal():
    run = _twin_goals_run()
    run.player = run.secondary_goal
    assert run._maze_cleared() is True


def test_maze_cleared_via_the_primary_goal_still_works_with_twin_goals_active():
    run = _twin_goals_run()
    run.player = run.goal
    assert run._maze_cleared() is True


def test_pellets_never_double_spawn_on_the_same_cell():
    run = _twin_goals_run()
    positions = [p.pos for p in run.pellets]
    assert len(positions) == len(set(positions))


def test_bonus_cluster_adds_pellets_beyond_the_normal_scattered_spawn():
    with_twin_goals = _twin_goals_run(seed=2)
    without = LabyrinthRun(seed=2)
    without.maze_index = 31
    without._begin_maze()
    # Not an exact equality (scattered spawn count depends on open-cell
    # count, unaffected by Twin Goals) -- just confirms the cluster added
    # at least some pellets on top of it, when a secondary goal exists.
    if with_twin_goals.secondary_goal is not None:
        assert len(with_twin_goals.pellets) >= len(without.pellets)


def test_rotate_maze_transforms_the_secondary_goal_consistently():
    run = LabyrinthRun(seed=4)
    run.augment_build.acquire(TwinGoalsAugment())
    run.augment_build.acquire(RotatingMazeAugment())
    run.maze_index = 31
    run._begin_maze()
    assert run.secondary_goal is not None  # otherwise this test proves nothing

    n = run.cols
    before_secondary = run.secondary_goal
    run._rotate_maze()
    assert run.secondary_goal == rotate_cell_cw(before_secondary, n)


# ── Popups ────────────────────────────────────────────────────────────────


def test_popups_expire_after_popup_duration(run):
    run.add_popup(run.player, "+1.0s", (0, 0, 0))
    assert len(run.popups) == 1
    run.popups[0].created_at -= POPUP_DURATION_SECONDS + 0.1  # simulate time passing
    run.update()
    assert run.popups == []


def test_restart_clears_popups():
    run = LabyrinthRun()
    run.add_popup(run.player, "+1.0s", (0, 0, 0))
    assert run.popups != []
    run.restart()
    assert run.popups == []


def test_restart_clears_teleport_animation():
    run = _teleport_run()
    run.move((1, 0))
    assert run.teleport_animation is not None
    run.restart()
    assert run.teleport_animation is None


# ── move() combo pass-through (junction_stop_count) ──────────────────────
# A longer corridor with a junction partway through (branch opening at
# (3, 1)), so a plain move stops early but a combo can be told to continue.

JUNCTION_CORRIDOR_GRID = [
    [1, 1, 1, 1, 1, 1],
    [1, 0, 0, 0, 0, 1],
    [1, 1, 1, 0, 1, 1],
]


def _junction_corridor_run() -> LabyrinthRun:
    run = LabyrinthRun()
    run.grid = [row[:] for row in JUNCTION_CORRIDOR_GRID]
    run.player = (1, 1)
    run.goal = (4, 1)
    run.pellets = []
    run.gold_pellets = []
    run.hazards = []
    return run


def test_move_defaults_to_stopping_at_the_first_junction():
    run = _junction_corridor_run()
    run.move((1, 0))
    assert run.player == (3, 1)  # (3,1) has a 3rd opening down to (3,2) -- a junction


def test_move_with_spacebar_combo_ignores_junctions_and_runs_to_the_wall():
    run = _junction_corridor_run()
    run.move((1, 0), junction_stop_count=None)
    assert run.player == (4, 1)  # dead end, past the junction


def test_move_with_number_combo_collects_pellets_it_now_passes_through():
    run = _junction_corridor_run()
    run.pellets = [Pellet((3, 1), value=1.0)]  # sits on the junction cell itself
    before = run.time.amount
    run.move((1, 0), junction_stop_count=2)
    assert run.player == (4, 1)
    assert run.pellets == []
    assert run.time.amount == pytest.approx(before + 1.0 * run.build.pellet_value_multiplier)


# ── Freeze pellet (runtime effect) ──────────────────────────────────────


def test_freeze_active_is_false_by_default(run):
    assert run.freeze_active is False


def test_freeze_active_is_true_until_the_deadline():
    run = LabyrinthRun(seed=1)
    run.freeze_until = time.monotonic() + 10.0
    assert run.freeze_active is True


def test_freeze_active_is_false_once_the_deadline_passes():
    run = LabyrinthRun(seed=1)
    run.freeze_until = time.monotonic() - 0.01
    assert run.freeze_active is False


def test_visible_and_discovered_cells_returns_none_while_frozen_even_with_fog_active():
    run = _fog_run()
    run.freeze_until = time.monotonic() + 10.0
    assert run.visible_and_discovered_cells() is None


def test_update_does_not_tick_the_rotation_timer_while_frozen():
    run = _rotating_run()
    run.freeze_until = time.monotonic() + 10.0
    run.rotation_timer.remaining = 1.0
    run.rotation_timer._last_tick -= 30.0  # simulate 30s having passed
    run.update()
    assert run.rotation_timer.remaining == 1.0  # untouched -- frozen, same as on_break


def test_update_resyncs_the_rotation_timer_once_a_freeze_window_ends():
    run = _rotating_run()
    run.freeze_until = time.monotonic() - 0.01  # already expired
    run._was_frozen = True  # simulate having just been frozen last frame
    run.rotation_timer._last_tick -= 30.0  # stale, as if 30s passed while frozen
    run.update()
    # resync() reset the reference point to ~now -- if it hadn't, this
    # update() would have charged the whole stale 30s against `remaining`.
    assert run.rotation_timer.remaining == pytest.approx(ROTATE_INTERVAL_BASE_SECONDS, abs=0.5)


def test_begin_maze_resets_hazard_contacts_and_pending_chain_multiplier():
    run = LabyrinthRun(seed=1)
    run.hazard_contacts_this_maze = 5
    run.pending_chain_multiplier = 3.0
    run._begin_maze()
    assert run.hazard_contacts_this_maze == 0
    assert run.pending_chain_multiplier == 1.0


def test_begin_maze_does_not_reset_freeze_until():
    """Freeze is a wall-clock window, not a per-maze resource -- it should keep working into the next maze."""
    run = LabyrinthRun(seed=1)
    deadline = time.monotonic() + 10.0
    run.freeze_until = deadline
    run._begin_maze()
    assert run.freeze_until == deadline


def test_restart_clears_freeze_until():
    run = LabyrinthRun(seed=1)
    run.freeze_until = time.monotonic() + 10.0
    run.restart()
    assert run.freeze_until is None


# ── PauseMenu (tiny cursor state, mirrors menu/__init__.py::MainMenu) ────


def test_pause_menu_starts_at_the_first_option():
    menu = PauseMenu()
    assert menu.cursor == 0
    assert menu.selected == PAUSE_OPTIONS[0][0]


def test_pause_menu_move_cursor_wraps_forward_and_backward():
    menu = PauseMenu()
    menu.move_cursor(-1)
    assert menu.cursor == len(PAUSE_OPTIONS) - 1  # wraps backward from 0
    menu.move_cursor(1)
    assert menu.cursor == 0
    menu.move_cursor(1)
    assert menu.cursor == 1 % len(PAUSE_OPTIONS)


def test_pause_menu_selected_matches_the_option_at_the_cursor():
    menu = PauseMenu()
    for i in range(len(PAUSE_OPTIONS)):
        menu.cursor = i
        assert menu.selected == PAUSE_OPTIONS[i][0]
