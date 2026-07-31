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
    BOSS_INTERVAL, BOSS_BASE_HP, BOSS_HP_STEP, BOSS_BASE_DAMAGE,
    ENEMY_TIME_PENALTY, SPEED_BONUS_TIME, POPUP_DURATION_SECONDS,
)
from maze_game.progression.run import dimensions_for_maze, TimeResource, LabyrinthRun
from maze_game.progression.entities.hazards import Pellet, GoldPellet, Enemy
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


@pytest.fixture(autouse=True)
def _isolate_gold_file(tmp_path, monkeypatch):
    """
    Every LabyrinthRun() in this file (there are dozens, unlike Game's
    single history_path-taking fixture) should never touch the real
    on-disk gold.json -- patching the module-level default the __init__
    falls back to isolates all of them at once.
    """
    monkeypatch.setattr("maze_game.progression.run.DEFAULT_GOLD_PATH", tmp_path / "gold.json")


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
    assert run.player not in [g.pos for g in run.gold_pellets]
    assert run.goal not in [g.pos for g in run.gold_pellets]


def test_gold_pellets_never_overlap_pellets():
    """Regardless of which spawns first, a gold pellet must never land on the same cell as a time pellet."""
    for seed in range(20):
        run = LabyrinthRun(seed=seed)
        pellet_positions = {p.pos for p in run.pellets}
        gold_positions = {g.pos for g in run.gold_pellets}
        assert pellet_positions.isdisjoint(gold_positions)


def test_gold_pellets_are_empty_on_a_boss_maze():
    run = LabyrinthRun()
    run.maze_index = BOSS_INTERVAL
    run._begin_maze()
    assert run.gold_pellets == []


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
    assert "card_select" in run.events
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


def test_completing_the_final_maze_sets_completed_run_not_on_break():
    run = LabyrinthRun()
    for maze_num in range(1, LABYRINTH_TOTAL_MAZES + 1):
        if run.boss is not None:
            run.boss.hp = 0
        else:
            run.player = run.goal
        run.update()
        while run.on_break and maze_num != LABYRINTH_TOTAL_MAZES:
            run.choose_break_card(0)  # may need to clear more than one stacked break (e.g. shop then augment)
    assert run.completed_run is True
    assert run.on_break is False
    assert run.maze_index == LABYRINTH_TOTAL_MAZES


# ── New pacing: power-up / modifier / boss cadence ───────────────────────


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


def test_maze_29_to_30_transition_is_seamless_and_maze_30_is_a_boss_maze():
    """29 isn't a group/augment boundary, so entering maze 30 (the first boss maze) has no break screen at all."""
    run = LabyrinthRun()
    run.maze_index = 29
    run._advance()
    assert run.on_break is False
    assert run.maze_index == 30
    assert run.boss is not None
    assert run.goal is None


def test_maze_30_completion_stacks_shop_then_augment_before_maze_31():
    """
    30 is a multiple of 5, 10, AND BOSS_INTERVAL(30) -- clearing the boss at
    maze 30 still stacks the same shop-then-augment breaks as any other
    double-boundary maze before maze 31 begins (31 itself isn't a boss maze).
    """
    run = LabyrinthRun()
    run.maze_index = 30
    run._advance()
    assert run.break_kind == "shop"
    run.choose_break_card(0)
    assert run.break_kind == "augment"
    run.choose_break_card(0)
    assert run.on_break is False
    assert run.maze_index == 31
    assert run.boss is None


def test_maze_99_to_100_transition_is_seamless_and_maze_100_is_the_hardest_boss():
    """
    99 isn't a boundary, so maze 100 (the special final boss) begins with no
    preceding break, exactly like maze 30/60/90's transitions. Its HP is
    deliberately the highest of the run (boss_encounter_index special-cases
    the final maze) -- "especially hard" isn't accidentally undercut by
    BOSS_INTERVAL=30 giving fewer total encounters than the old scheme.
    """
    run = LabyrinthRun()
    run.maze_index = 99
    run._advance()
    assert run.on_break is False
    assert run.maze_index == LABYRINTH_TOTAL_MAZES
    assert run.boss is not None
    assert run.boss.hp == BOSS_BASE_HP + BOSS_HP_STEP * 4  # boss_encounter_index(100) == 4, matches the old scheme's final HP
    assert run.boss.hp > BOSS_BASE_HP + BOSS_HP_STEP * 2  # strictly harder than maze 90's encounter (index 2)


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


def test_repeated_augment_breaks_level_up_the_only_shipped_augment():
    """
    With ALL_AUGMENTS at its current length of 1 (teleporters), every
    modifier break necessarily offers a single forced card -- expected
    graceful degradation, not a bug. Driving all 9 augment breaks in a run
    (mazes 10..90) should just keep leveling teleporters up.
    """
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
        if run.boss is not None:
            run.boss.hp = 0
        else:
            run.player = run.goal
        run.update()
        while run.on_break:
            run.choose_break_card(0)  # may need to clear more than one stacked break (e.g. shop then augment)


def test_same_seed_produces_identical_maze_and_entities():
    a = LabyrinthRun(seed=999)
    b = LabyrinthRun(seed=999)
    assert a.grid == b.grid
    assert [p.pos for p in a.pellets] == [p.pos for p in b.pellets]
    assert [e.pos for e in a.enemies] == [e.pos for e in b.enemies]
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
    run.gold_pellets = []
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


def test_move_takes_enemy_damage_along_the_slide_path_and_enemy_persists():
    run = _corridor_run()
    enemy = Enemy((2, 1))
    run.enemies = [enemy]
    before = run.time.amount
    run.move((1, 0))
    assert run.time.amount == pytest.approx(max(0.0, before - ENEMY_TIME_PENALTY))
    assert run.enemies == [enemy]  # persistent hazard, not consumed


def test_move_hitting_an_enemy_adds_a_popup_at_its_position():
    run = _corridor_run()
    run.enemies = [Enemy((2, 1))]
    run.move((1, 0))
    assert len(run.popups) == 1
    assert run.popups[0].pos == (2, 1)
    assert run.popups[0].text == f"-{ENEMY_TIME_PENALTY:.1f}s"


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


def test_move_hitting_an_enemy_appends_move_and_enemy_hit_events():
    run = _corridor_run()
    run.enemies = [Enemy((2, 1))]
    run.move((1, 0))
    assert run.events == ["move", "enemy_hit"]


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
    run.enemies = []
    run.boss = None
    run._teleport_map = {(2, 1): (3, 1)}
    return run


def test_moving_through_a_teleporter_appends_the_teleport_event_not_move():
    run = _teleport_run()
    run.move((1, 0))
    assert run.player == (3, 1)
    assert run.events == ["teleport"]


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


# (5, 1) has zero open grid neighbours -- only the extra_edges link to
# (1, 1) below reaches it, same as a real teleporter-only pocket.
BOSS_TELEPORT_POCKET_GRID = [
    [1, 1, 1, 1, 1, 1, 1],
    [1, 0, 0, 1, 1, 0, 1],
    [1, 1, 1, 1, 1, 1, 1],
]


def test_move_against_an_active_boss_reaches_it_through_a_teleporter_only_pocket():
    """
    Regression test: LabyrinthRun.move() used to call boss.advance() without
    the run's teleport map, so a boss placed inside a pocket only reachable
    through a teleporter (a real possibility -- see augments/teleporters.py
    and _begin_maze()'s comment on ctx.goal doubling as the boss's
    placement) crashed with a KeyError the instant it hit an active turn.
    """
    run = _corridor_run()
    run.grid = [row[:] for row in BOSS_TELEPORT_POCKET_GRID]
    run.player = (1, 1)
    run.goal = None
    run.boss = Boss((5, 1), hp=5)
    run.boss.move_count = 1  # force active phase on this move
    run._teleport_map = {(1, 1): (5, 1), (5, 1): (1, 1)}
    run.move((1, 0))
    assert run.boss.pos == (1, 1)  # stepped through the teleporter link toward the player's pre-move position


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
    assert "wall_break" in run.events


def test_wall_breaker_without_a_charge_stops_at_the_wall():
    run = _wall_breaker_run()
    run.move((1, 0), use_wall_breaker=True)
    assert run.grid[1][2] == 1  # unchanged
    assert run.player == (1, 1)  # never moved -- stopped immediately at the wall
    assert "wall_break" not in run.events


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
    assert "wall_break" not in run.events


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
    assert run.events == ["laser"]


def test_activate_laser_without_a_charge_is_a_no_op():
    run = _laser_room_run()
    enemy = Enemy((2, 1))
    run.enemies = [enemy]
    run.activate_laser()
    assert run.enemies == [enemy]
    assert run.events == []


def test_activate_stopwatch_pauses_time_and_blocks_movement_then_resyncs():
    """Mirrors test_choosing_a_perk_does_not_retroactively_charge_the_break_duration -- same resync fix, applied to the Stopwatch pause."""
    run = _corridor_run()
    run.loadout.charges["stopwatch"] = 1
    run.activate_stopwatch()
    assert run.stopwatch_until is not None
    assert run.loadout.charges["stopwatch"] == 0
    assert run.events == ["stopwatch"]

    pos_before = run.player
    run.move((1, 0))
    assert run.player == pos_before  # movement blocked while paused
    assert run.events == ["stopwatch"]  # move() was gated -- no "move" event appended

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
    assert run.events == []


def test_activate_squeaky_toy_sets_a_timestamp_and_needs_no_charge():
    run = _corridor_run()
    assert run.last_squeak_at is None
    run.activate_squeaky_toy()
    assert run.last_squeak_at is not None
    assert run.loadout.charges.get("squeaky_toy", 0) == 0  # unlimited -- never consumes a charge
    assert run.events == ["squeak"]


def test_activate_squeaky_toy_is_a_no_op_once_failed():
    run = _corridor_run()
    run.time.amount = 0.0
    run.update()
    assert run.failed is True
    assert run.events == ["fail"]
    run.activate_squeaky_toy()
    assert run.last_squeak_at is None
    assert run.events == ["fail"]  # gated -- no "squeak" appended
