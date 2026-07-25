"""
Tests for maze_game.progression -- dimension ramp, per-maze time limits,
and the LabyrinthRun state machine (sequencing, group breaks, timeout
failure, restart).
"""

import time

import pytest

from maze_game.constants import (
    MIN_DIMENSION, MAX_DIMENSION, DIMENSION_STEP,
    LABYRINTH_GROUP_SIZE, LABYRINTH_TOTAL_MAZES,
    LABYRINTH_TIME_BASE, LABYRINTH_TIME_PER_TURN,
)
from maze_game.progression import (
    dimensions_for_maze, count_direction_changes, estimate_time_limit, LabyrinthRun,
)


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


# ── count_direction_changes ───────────────────────────────────────────────
# Grids below are built so every intermediate path cell has exactly 2 open
# neighbours (a plain corridor cell or corner, never a junction) *unless* a
# test is specifically checking the forced-stop-at-a-junction case -- that
# keeps these tests isolated to one behaviour at a time.


def test_count_direction_changes_trivial_path():
    grid = [[1, 1, 1], [1, 0, 1], [1, 1, 1]]
    assert count_direction_changes(grid, [(1, 1)]) == 0


def test_count_direction_changes_straight_line():
    grid = [
        [1, 1, 1],
        [1, 0, 1],
        [1, 0, 1],
        [1, 0, 1],
        [1, 0, 1],
        [1, 1, 1],
    ]
    path = [(1, 1), (1, 2), (1, 3), (1, 4)]
    assert count_direction_changes(grid, path) == 1


def test_count_direction_changes_one_turn():
    grid = [
        [1, 1, 1, 1, 1],
        [1, 0, 1, 1, 1],
        [1, 0, 1, 1, 1],
        [1, 0, 0, 0, 1],
        [1, 1, 1, 1, 1],
    ]
    path = [(1, 1), (1, 2), (1, 3), (2, 3), (3, 3)]
    assert count_direction_changes(grid, path) == 2


def test_count_direction_changes_zigzag():
    grid = [
        [1, 1, 1, 1, 1],
        [1, 0, 0, 1, 1],
        [1, 1, 0, 0, 1],
        [1, 1, 1, 0, 1],
        [1, 1, 1, 1, 1],
    ]
    path = [(1, 1), (2, 1), (2, 2), (3, 2), (3, 3)]
    assert count_direction_changes(grid, path) == 4


def test_count_direction_changes_counts_a_forced_stop_at_a_pass_through_junction():
    """
    Regression test for the bug this was built to catch: the path runs
    straight through (2,2) without turning, but (2,2) is a junction (it also
    has an opening down to (2,3) that the path doesn't use) -- slide()
    force-stops there regardless, so continuing costs an *extra* press that
    pure direction-change counting misses entirely.
    """
    grid = [
        [1, 1, 1, 1, 1],
        [1, 0, 0, 0, 1],
        [1, 1, 0, 1, 1],
        [1, 1, 0, 1, 1],
        [1, 1, 1, 1, 1],
    ]
    path = [(1, 1), (2, 1), (3, 1)]  # straight through (2,1), which has a 3rd opening down to (2,2)
    # (2,1) neighbours: (1,1) open, (3,1) open, (2,2) open -> 3 open neighbours, a junction.
    assert count_direction_changes(grid, path) == 2  # not 1 -- the forced stop needs its own press


# ── estimate_time_limit ───────────────────────────────────────────────────


def test_estimate_time_limit_matches_formula_on_a_simple_grid():
    # A trivial 5x5 grid with a straight-line path (1,1)->(1,3).
    grid = [
        [1, 1, 1, 1, 1],
        [1, 0, 1, 1, 1],
        [1, 0, 1, 1, 1],
        [1, 0, 1, 1, 1],
        [1, 1, 1, 1, 1],
    ]
    limit = estimate_time_limit(grid, (1, 1), (1, 3))
    assert limit == pytest.approx(LABYRINTH_TIME_BASE + LABYRINTH_TIME_PER_TURN * 1)


def test_estimate_time_limit_increases_with_more_turns():
    straight = [
        [1, 1, 1, 1, 1],
        [1, 0, 1, 1, 1],
        [1, 0, 1, 1, 1],
        [1, 0, 1, 1, 1],
        [1, 1, 1, 1, 1],
    ]
    with_a_turn = [
        [1, 1, 1, 1, 1],
        [1, 0, 1, 1, 1],
        [1, 0, 0, 0, 1],
        [1, 1, 1, 0, 1],
        [1, 1, 1, 1, 1],
    ]
    t_straight = estimate_time_limit(straight, (1, 1), (1, 3))
    t_turn = estimate_time_limit(with_a_turn, (1, 1), (3, 3))
    assert t_turn > t_straight


# ── LabyrinthRun ──────────────────────────────────────────────────────────


@pytest.fixture
def run():
    return LabyrinthRun()


def test_starts_at_maze_1_with_min_dimensions(run):
    assert run.maze_index == 1
    assert (run.cols, run.rows) == (MIN_DIMENSION, MIN_DIMENSION)
    assert run.on_break is False
    assert run.failed is False
    assert run.completed_run is False
    assert run.finished is False


def test_update_advances_elapsed(run):
    time.sleep(0.05)
    run.update()
    assert run.elapsed > 0.0


def test_completing_a_non_group_boundary_maze_advances_seamlessly(run):
    assert run.maze_index % LABYRINTH_GROUP_SIZE != 0
    run.player = run.goal
    run.update()
    assert run.maze_index == 2
    assert run.on_break is False
    assert run.finished is False  # finished is per-maze; the new maze isn't finished
    assert run.elapsed == 0.0     # fresh timer for the new maze


def test_completing_the_last_maze_of_a_group_triggers_a_break():
    run = LabyrinthRun()
    for _ in range(LABYRINTH_GROUP_SIZE):
        assert run.on_break is False
        run.player = run.goal
        run.update()
    assert run.on_break is True
    assert run.maze_index == LABYRINTH_GROUP_SIZE  # doesn't advance until resume()


def test_resume_advances_past_the_break():
    run = LabyrinthRun()
    for _ in range(LABYRINTH_GROUP_SIZE):
        run.player = run.goal
        run.update()
    assert run.on_break is True

    run.resume()
    assert run.on_break is False
    assert run.maze_index == LABYRINTH_GROUP_SIZE + 1
    assert (run.cols, run.rows) == (MIN_DIMENSION + DIMENSION_STEP, MIN_DIMENSION + DIMENSION_STEP)


def test_resume_is_a_no_op_when_not_on_break(run):
    assert run.on_break is False
    run.resume()
    assert run.maze_index == 1


def test_timeout_fails_the_run(run):
    run._start = time.time() - (run.time_limit + 5)
    run.update()
    assert run.failed is True
    assert run.elapsed == run.time_limit


def test_move_is_a_no_op_once_failed(run):
    run._start = time.time() - (run.time_limit + 5)
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


def test_restart_resets_everything(run):
    run._start = time.time() - (run.time_limit + 5)
    run.update()
    assert run.failed is True

    run.restart()
    assert run.maze_index == 1
    assert run.failed is False
    assert run.on_break is False
    assert run.completed_run is False
    assert (run.cols, run.rows) == (MIN_DIMENSION, MIN_DIMENSION)


def test_completing_the_final_maze_sets_completed_run_not_on_break():
    run = LabyrinthRun()
    for maze_num in range(1, LABYRINTH_TOTAL_MAZES + 1):
        run.player = run.goal
        run.update()
        if maze_num % LABYRINTH_GROUP_SIZE == 0 and maze_num != LABYRINTH_TOTAL_MAZES:
            assert run.on_break is True
            run.resume()
    assert run.completed_run is True
    assert run.on_break is False
    assert run.maze_index == LABYRINTH_TOTAL_MAZES


def test_group_number_and_total_groups(run):
    assert run.group_number == 1
    assert run.total_groups == LABYRINTH_TOTAL_MAZES // LABYRINTH_GROUP_SIZE

    for _ in range(LABYRINTH_GROUP_SIZE):
        run.player = run.goal
        run.update()
    run.resume()
    assert run.group_number == 2
