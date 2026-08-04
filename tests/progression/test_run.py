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
)
from maze_game.progression.run import dimensions_for_maze, is_milestone_maze, TimeResource, LabyrinthRun
from maze_game.progression.entities.hazards import Pellet, GoldPellet, Hazard, load_gold_total
from maze_game.progression.shop.perks import ALL_PERKS, Perk
from maze_game.progression.augments.teleporters import TeleportersAugment
from maze_game.progression.augments.doors import DoorKeyPair, Key
from maze_game.progression.augments.multi_level import FloorLink

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


def test_floors_can_receive_pellets_not_just_stay_empty_transit_rooms():
    """
    A floor's entire blob used to be excluded from pellet/hazard spawning
    (ctx.reserved protects the whole blob for PLACEMENT safety against
    other augments, which used to double as the spawn-exclude set too) --
    now only its four special stairs cells are excluded, so a floor reads
    as a real place with something in it, not just an empty corridor.
    Checks several seeds since spawning is density-driven and floors are
    small, so no single seed is guaranteed to prove the point on its own.
    """
    from maze_game.progression.augments.multi_level import MultiLevelAugment

    found = False
    for seed in range(20):
        run = LabyrinthRun(seed=seed)
        for _ in range(4):
            run.augment_build.acquire(MultiLevelAugment())
        run._begin_maze()  # re-run _begin_maze() now that multi_level is active
        if not run.floors:
            continue
        pellet_positions = {p.pos for p in run.pellets} | {g.pos for g in run.gold_pellets}
        for link in run.floors:
            interior = link.blob - {link.entrance, link.floor_start, link.floor_exit, link.return_landing}
            if pellet_positions & interior:
                found = True
                break
        if found:
            break
    assert found, "expected at least one seed to spawn a pellet/gold pellet inside a floor's own interior"


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
    run.hazards = []
    run._teleport_map = {(2, 1): (3, 1)}
    return run


def test_moving_through_a_teleporter_appends_the_teleport_event_not_move():
    run = _teleport_run()
    run.move((1, 0))
    assert run.player == (3, 1)
    assert run.events == ["teleport"]


def test_plain_teleporters_never_touch_the_floor_stack():
    """A plain teleporter pair isn't in run.floors at all, so it must never
    push/pop _floor_stack -- only a cell that's specifically some
    FloorLink's own floor_start/return_landing does."""
    run = _teleport_run()
    run.floors = []
    run.move((1, 0))
    assert run.player == (3, 1)
    assert run._floor_stack == []


# A wide corridor, (1,1)-(9,1), used to drive stairs (multi_level.py)
# push/pop deterministically -- two FloorLink pairs chained one after the
# other (floor1: (2,1)->(4,1) up, (6,1)->(8,1) down) so a single move()
# through each teleport-mapped cell exercises one push or pop at a time.
FLOOR_GRID = [
    [1] * 11,
    [1] + [0] * 9 + [1],
    [1] * 11,
]


def _floor_run(floors, teleport_map) -> LabyrinthRun:
    run = LabyrinthRun()
    run.grid = [row[:] for row in FLOOR_GRID]
    run.player = (1, 1)
    run.pellets = []
    run.hazards = []
    run.floors = floors
    run._teleport_map = teleport_map
    run._floor_stack = []
    return run


def _floor_link(entrance, floor_start, floor_exit, return_landing, floor=1, mandatory=True, color_index=0):
    return FloorLink(
        entrance=entrance, floor_start=floor_start, floor_exit=floor_exit, return_landing=return_landing,
        mandatory=mandatory, color_index=color_index, floor=floor,
        blob=frozenset({floor_start, floor_exit}),
    )


def test_entering_a_floors_floor_start_pushes_the_stack():
    link = _floor_link(entrance=(2, 1), floor_start=(4, 1), floor_exit=(6, 1), return_landing=(8, 1))
    run = _floor_run([link], {(2, 1): (4, 1), (6, 1): (8, 1)})

    run.move((1, 0))  # (1,1) -> enters (2,1) -> warps to floor_start (4,1)
    assert run.player == (4, 1)
    assert run._floor_stack == [link]


def test_returning_via_a_floors_return_landing_pops_the_stack():
    link = _floor_link(entrance=(2, 1), floor_start=(4, 1), floor_exit=(6, 1), return_landing=(8, 1))
    run = _floor_run([link], {(2, 1): (4, 1), (6, 1): (8, 1)})
    run.player = (4, 1)
    run._floor_stack = [link]

    run.move((1, 0))  # (4,1) -> enters (6,1) -> warps to return_landing (8,1)
    assert run.player == (8, 1)
    assert run._floor_stack == []


def test_nested_floors_return_to_the_parent_floors_view_not_top_level():
    outer = _floor_link(entrance=(2, 1), floor_start=(4, 1), floor_exit=(9, 1), return_landing=(10, 1), floor=1)
    inner = _floor_link(entrance=(5, 1), floor_start=(6, 1), floor_exit=(7, 1), return_landing=(8, 1), floor=2)
    teleport_map = {
        (2, 1): (4, 1), (5, 1): (6, 1),  # both "up" trips
        (7, 1): (8, 1), (9, 1): (10, 1),  # both "down" trips
    }
    run = _floor_run([outer, inner], teleport_map)

    run.move((1, 0))  # -> outer.floor_start (4,1)
    assert run._floor_stack == [outer]

    run.move((1, 0))  # (4,1) -> (5,1) enters inner's entrance -> inner.floor_start (6,1)
    assert run._floor_stack == [outer, inner]

    run.move((1, 0))  # (6,1) -> (7,1) is inner's floor_exit -> inner.return_landing (8,1)
    assert run._floor_stack == [outer], "leaving the nested floor must return to the OUTER floor's view, not top-level"

    run.move((1, 0))  # (8,1) -> (9,1) is outer's floor_exit -> outer.return_landing (10,1)
    assert run._floor_stack == []


def test_current_view_bounds_is_none_at_top_level_and_the_blobs_bbox_inside_a_floor():
    link = _floor_link(entrance=(2, 1), floor_start=(4, 1), floor_exit=(6, 1), return_landing=(8, 1))
    run = _floor_run([link], {(2, 1): (4, 1), (6, 1): (8, 1)})
    assert run.current_view_bounds is None

    run._floor_stack = [link]
    min_x = min(x for x, _y in link.blob)
    min_y = min(y for _x, y in link.blob)
    max_x = max(x for x, _y in link.blob)
    max_y = max(y for _x, y in link.blob)
    assert run.current_view_bounds == (min_x, min_y, max_x - min_x + 1, max_y - min_y + 1)


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
