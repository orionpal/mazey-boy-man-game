"""
Tests for maze_game.progression.run -- dimension ramp, the persistent
TimeResource, the LabyrinthRun state machine (sequencing, shop-choice
breaks, boss mazes, timeout failure, restart), and pellet/enemy/item
contact via move(). Perk/Build and Item/Loadout are tested in isolation
under tests/progression/shop/.
"""

import time

import pytest

from maze_game.constants import (
    MIN_DIMENSION, MAX_DIMENSION, DIMENSION_STEP,
    LABYRINTH_GROUP_SIZE, LABYRINTH_TOTAL_MAZES, LABYRINTH_START_TIME,
    BOSS_INTERVAL, BOSS_BASE_DAMAGE, ENEMY_TIME_PENALTY, SPEED_BONUS_TIME,
)
from maze_game.progression.run import dimensions_for_maze, TimeResource, LabyrinthRun
from maze_game.progression.entities.hazards import Pellet, Enemy
from maze_game.progression.entities.boss import Boss
from maze_game.progression.shop.perks import ALL_PERKS, Perk
from maze_game.progression.shop.items import ALL_ITEMS

# A trivial straight 3-cell corridor, (1,1)-(2,1)-(3,1), used to drive
# move() deterministically instead of a randomly-generated maze.
CORRIDOR_GRID = [
    [1, 1, 1, 1, 1],
    [1, 0, 0, 0, 1],
    [1, 1, 1, 1, 1],
]


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


def test_dimensions_are_monotonically_nondecreasing():
    prev = dimensions_for_maze(1)
    for i in range(2, LABYRINTH_TOTAL_MAZES + 1):
        cur = dimensions_for_maze(i)
        assert cur[0] >= prev[0] and cur[1] >= prev[1]
        prev = cur


def test_dimensions_cap_at_max_dimension():
    assert dimensions_for_maze(LABYRINTH_TOTAL_MAZES) == (MAX_DIMENSION, MAX_DIMENSION)


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


def test_update_ticks_the_time_resource(run):
    before = run.time.amount
    time.sleep(0.05)
    run.update()
    assert run.time.amount < before


def test_pellets_and_enemies_never_spawn_on_start_or_goal(run):
    assert run.player not in [p.pos for p in run.pellets]
    assert run.goal not in [p.pos for p in run.pellets]
    assert run.player not in [e.pos for e in run.enemies]
    assert run.goal not in [e.pos for e in run.enemies]


def test_enemies_are_empty_before_the_unlock_maze(run):
    assert run.enemies == []


def test_completing_a_non_group_boundary_maze_advances_seamlessly(run):
    assert run.maze_index % LABYRINTH_GROUP_SIZE != 0
    run.player = run.goal
    run.update()
    assert run.maze_index == 2
    assert run.on_break is False
    assert run.finished is False  # finished is per-maze; the new maze isn't finished


def test_completing_the_last_maze_of_a_group_offers_shop_choices():
    """
    Shop choices are now a random draw of 3 from the combined pool of all
    perks and items (confirmed: this replaces the old guaranteed-all-3-perks
    behavior), so this only checks length and pool membership, not exact
    identity.
    """
    run = LabyrinthRun()
    for _ in range(LABYRINTH_GROUP_SIZE):
        assert run.on_break is False
        run.player = run.goal
        run.update()
    assert run.on_break is True
    assert run.maze_index == LABYRINTH_GROUP_SIZE  # doesn't advance until choose_shop_card()
    assert len(run.shop_choices) == 3
    pool = list(ALL_PERKS) + list(ALL_ITEMS)
    assert all(card in pool for card in run.shop_choices)


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
    assert run.maze_index == LABYRINTH_GROUP_SIZE + 1
    assert (run.cols, run.rows) == (MIN_DIMENSION + DIMENSION_STEP, MIN_DIMENSION + DIMENSION_STEP)
    if isinstance(chosen, Perk):
        assert run.build.picks == {chosen.id: 1}
    else:
        assert run.loadout.picks == {chosen.id: 1}


def test_choose_shop_card_is_a_no_op_when_not_on_break(run):
    assert run.on_break is False
    run.choose_shop_card(0)
    assert run.maze_index == 1
    assert run.build.picks == {}


def test_shop_cursor_starts_at_zero_and_wraps_with_move_shop_cursor():
    run = LabyrinthRun()
    for _ in range(LABYRINTH_GROUP_SIZE):
        run.player = run.goal
        run.update()
    assert run.on_break is True
    assert run.shop_cursor == 0

    run.move_shop_cursor(-1)
    assert run.shop_cursor == len(run.shop_choices) - 1  # wraps backward
    run.move_shop_cursor(1)
    assert run.shop_cursor == 0
    run.move_shop_cursor(1)
    assert run.shop_cursor == 1


def test_move_shop_cursor_is_a_no_op_when_not_on_break(run):
    assert run.on_break is False
    run.move_shop_cursor(1)
    assert run.shop_cursor == 0


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


def test_completing_the_final_maze_sets_completed_run_not_on_break():
    run = LabyrinthRun()
    for maze_num in range(1, LABYRINTH_TOTAL_MAZES + 1):
        if run.boss is not None:
            run.boss.hp = 0
        else:
            run.player = run.goal
        run.update()
        if run.on_break and maze_num != LABYRINTH_TOTAL_MAZES:
            run.choose_shop_card(0)
    assert run.completed_run is True
    assert run.on_break is False
    assert run.maze_index == LABYRINTH_TOTAL_MAZES


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


def test_completing_a_maze_slowly_does_not_award_a_speed_bonus(run):
    run._maze_started_at -= (run._par_seconds + 5.0)
    before = run.time.amount
    run.player = run.goal
    run.update()
    assert run.time.amount <= before  # no bonus, only the tiny real-time tick


# ── Boss mazes ────────────────────────────────────────────────────────────


def test_boss_maze_has_no_goal_pellets_or_enemies_and_a_boss():
    run = LabyrinthRun()
    run.maze_index = BOSS_INTERVAL
    run._begin_maze()
    assert run.goal is None
    assert run.pellets == []
    assert run.enemies == []
    assert run.boss is not None
    assert run.boss.hp > 0


def test_defeating_the_boss_clears_the_maze():
    run = LabyrinthRun()
    run.maze_index = BOSS_INTERVAL
    run._begin_maze()
    run.boss.hp = 0
    run.update()
    assert run.finished is True


# ── move() contact resolution ────────────────────────────────────────────


def _corridor_run() -> LabyrinthRun:
    run = LabyrinthRun()
    run.grid = [row[:] for row in CORRIDOR_GRID]
    run.player = (1, 1)
    run.goal = (3, 1)
    run.pellets = []
    run.enemies = []
    run.boss = None
    return run


def test_move_collects_a_pellet_along_the_slide_path():
    run = _corridor_run()
    run.pellets = [Pellet((2, 1), value=4.0)]
    before = run.time.amount
    run.move((1, 0))
    assert run.player == (3, 1)
    assert run.pellets == []
    assert run.time.amount == pytest.approx(before + 4.0 * run.build.pellet_value_multiplier)


def test_move_takes_enemy_damage_along_the_slide_path_and_enemy_persists():
    run = _corridor_run()
    enemy = Enemy((2, 1))
    run.enemies = [enemy]
    before = run.time.amount
    run.move((1, 0))
    assert run.time.amount == pytest.approx(max(0.0, before - ENEMY_TIME_PENALTY))
    assert run.enemies == [enemy]  # persistent hazard, not consumed


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
    run.enemies = []
    run.boss = None
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


def test_move_damages_an_idle_boss_without_costing_time():
    run = _corridor_run()
    run.goal = None
    run.boss = Boss((2, 1), hp=5)
    before_time = run.time.amount
    run.move((1, 0))  # move_count starts at 0 -> idle phase
    assert run.boss.hp == pytest.approx(5 - BOSS_BASE_DAMAGE * run.build.strength_multiplier)
    assert run.time.amount == pytest.approx(before_time)


def test_move_costs_time_against_an_active_boss():
    run = _corridor_run()
    run.goal = None
    # Starts at the far end of the corridor: stepping toward the player's
    # pre-move position (1,1) lands it on (2,1), which the player's slide
    # from (1,1) going right passes through -- contact happens this move.
    run.boss = Boss((3, 1), hp=5)
    run.boss.move_count = 1  # force active phase
    before_time = run.time.amount
    before_hp = run.boss.hp
    run.move((1, 0))
    assert run.boss.pos == (2, 1)
    assert run.boss.hp == before_hp  # no damage while active
    assert run.time.amount < before_time


# ── Active items (Q/W/E/R) ────────────────────────────────────────────────
# Hand-built grids drive LabyrinthRun.move()/activate_*() deterministically,
# same approach as the corridor grids above.

WALL_BREAKER_GRID = [
    [1, 1, 1, 1, 1],
    [1, 0, 1, 0, 1],
    [1, 1, 1, 1, 1],
]


def _wall_breaker_run() -> LabyrinthRun:
    run = _corridor_run()
    run.grid = [row[:] for row in WALL_BREAKER_GRID]
    run.player = (1, 1)
    run.goal = (3, 1)
    return run


def test_wall_breaker_breaks_a_non_border_wall_and_continues():
    run = _wall_breaker_run()
    run.loadout.charges["wall_breaker"] = 1
    run.move((1, 0), use_wall_breaker=True)
    assert run.grid[1][2] == 0  # the wall is now open
    assert run.player == (3, 1)  # slide continued through it
    assert run.loadout.charges["wall_breaker"] == 0


def test_wall_breaker_without_a_charge_stops_at_the_wall():
    run = _wall_breaker_run()
    run.move((1, 0), use_wall_breaker=True)
    assert run.grid[1][2] == 1  # unchanged
    assert run.player == (1, 1)  # never moved -- stopped immediately at the wall


def test_wall_breaker_refuses_to_break_the_border_wall():
    run = _corridor_run()
    run.grid = [
        [1, 1, 1],
        [1, 0, 1],
        [1, 1, 1],
    ]
    run.player = (1, 1)
    run.loadout.charges["wall_breaker"] = 5
    run.move((-1, 0), use_wall_breaker=True)
    assert run.grid[1][0] == 1  # border wall never broken
    assert run.player == (1, 1)  # never moved
    assert run.loadout.charges["wall_breaker"] == 5  # border check precedes the charge check


LASER_ROOM_GRID = [
    [1, 1, 1, 1, 1],
    [1, 0, 0, 0, 1],
    [1, 0, 0, 0, 1],
    [1, 0, 0, 0, 1],
    [1, 1, 1, 1, 1],
]


def _laser_room_run() -> LabyrinthRun:
    run = _corridor_run()
    run.grid = [row[:] for row in LASER_ROOM_GRID]
    run.player = (2, 2)  # centre of the 3x3 open room
    run.goal = None
    return run


def test_activate_laser_destroys_enemies_on_a_cardinal_ray_but_not_off_it():
    run = _laser_room_run()
    on_ray = Enemy((2, 1))       # directly above the player -- hit
    off_ray = Enemy((1, 1))      # corner, not on any of the 4 rays -- survives
    run.enemies = [on_ray, off_ray]
    run.loadout.charges["laser"] = 1
    run.activate_laser()
    assert run.enemies == [off_ray]
    assert run.loadout.charges["laser"] == 0


def test_activate_laser_without_a_charge_is_a_no_op():
    run = _laser_room_run()
    enemy = Enemy((2, 1))
    run.enemies = [enemy]
    run.activate_laser()
    assert run.enemies == [enemy]


def test_activate_stopwatch_pauses_time_and_blocks_movement_then_resyncs():
    """Mirrors test_choosing_a_perk_does_not_retroactively_charge_the_break_duration -- same resync fix, applied to the Stopwatch pause."""
    run = _corridor_run()
    run.loadout.charges["stopwatch"] = 1
    run.activate_stopwatch()
    assert run.stopwatch_until is not None
    assert run.loadout.charges["stopwatch"] == 0

    pos_before = run.player
    run.move((1, 0))
    assert run.player == pos_before  # movement blocked while paused

    before_time = run.time.amount
    run.update()  # still paused -- no tick, no resync yet
    assert run.time.amount == pytest.approx(before_time)
    assert run.stopwatch_until is not None

    run.stopwatch_until = time.monotonic() - 0.01  # force elapsed
    run.time._last_tick -= 30.0  # simulate 30s of real time spent paused
    run.update()  # the first frame after the pause ends
    assert run.stopwatch_until is None
    assert run.time.amount == pytest.approx(before_time, abs=0.05)  # resynced, pause not charged


def test_activate_stopwatch_without_a_charge_is_a_no_op():
    run = _corridor_run()
    run.activate_stopwatch()
    assert run.stopwatch_until is None


def test_activate_squeaky_toy_sets_a_timestamp_and_needs_no_charge():
    run = _corridor_run()
    assert run.last_squeak_at is None
    run.activate_squeaky_toy()
    assert run.last_squeak_at is not None
    assert run.loadout.charges.get("squeaky_toy", 0) == 0  # unlimited -- never consumes a charge


def test_activate_squeaky_toy_is_a_no_op_once_failed():
    run = _corridor_run()
    run.time.amount = 0.0
    run.update()
    assert run.failed is True
    run.activate_squeaky_toy()
    assert run.last_squeak_at is None
