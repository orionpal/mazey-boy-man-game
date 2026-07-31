"""
Tests for maze_game.game.Game -- timer behaviour, win condition,
post-finish freezing, adjustable dimensions, and run-history recording.
"""

import time

import pytest

from maze_game.constants import MIN_DIMENSION, MAX_DIMENSION
from maze_game.freeplay.game import Game, START_POS


@pytest.fixture
def game(tmp_path):
    """A Game wired to a throwaway history file so tests never touch the real run_history.json."""
    return Game(history_path=tmp_path / "history.json")


def test_new_maze_resets_state(game):
    assert game.player == START_POS
    assert game.finished is False
    assert game.elapsed == 0.0
    assert game.goal != START_POS


def test_update_advances_elapsed_time(game):
    time.sleep(0.05)
    game.update()
    assert game.elapsed > 0.0


def test_reaching_goal_finishes_and_records_best_time(game):
    game.player = game.goal  # simulate arriving at the goal
    game.update()
    assert game.finished is True
    assert game.best_time is not None
    assert game.best_time == game.elapsed


def test_timer_freezes_after_finish(game):
    game.player = game.goal
    game.update()
    finished_elapsed = game.elapsed
    time.sleep(0.05)
    game.update()
    assert game.elapsed == finished_elapsed


def test_move_is_a_no_op_after_finish(game):
    game.player = game.goal
    game.update()
    pos_before = game.player
    game.move((1, 0))
    assert game.player == pos_before


def test_best_time_only_improves(game):
    game.player = game.goal
    game.update()
    first_best = game.best_time
    assert first_best is not None

    game.new_maze()
    game.player = game.goal
    # Force a strictly worse elapsed time than the recorded best, and
    # confirm best_time does not regress.
    game._start = time.time() - (first_best + 10)
    game.update()
    assert game.best_time == first_best


def test_best_time_persists_across_new_maze(game):
    game.player = game.goal
    game.update()
    best = game.best_time
    game.new_maze()
    assert game.best_time == best


def test_best_time_is_specific_to_current_dimensions(game):
    """
    Regression test: best_time used to be a single value tracked across all
    dimensions, so a fast time on a small maze would still show as "best"
    after switching to a much larger (inherently slower) maze -- comparing
    times across different maze sizes doesn't mean anything.
    """
    game.set_dimensions(9, 9)
    game.player = game.goal
    game._start = time.time() - 2.0  # fast run on the small maze
    game.update()
    assert game.best_time == pytest.approx(2.0, abs=0.05)

    game.set_dimensions(31, 31)
    # No runs recorded yet at this size -- the 9x9 time must not leak in.
    assert game.best_time is None

    game.player = game.goal
    game._start = time.time() - 50.0  # much slower, but it's a much bigger maze
    game.update()
    assert game.best_time == pytest.approx(50.0, abs=0.05)

    # Switching back to 9x9 should show its own best again, unaffected by
    # the 31x31 run in between.
    game.set_dimensions(9, 9)
    assert game.best_time == pytest.approx(2.0, abs=0.05)


def test_best_time_is_seeded_from_history_on_a_fresh_session(tmp_path):
    """
    Regression test: best_time used to start at None on every Game()
    construction and was never seeded from the (already-loaded) persisted
    history, so a brand-new session could show a worse "best" than what was
    actually recorded from a previous session.
    """
    path = tmp_path / "history.json"
    first_session = Game(history_path=path)
    first_session.player = first_session.goal
    first_session._start = time.time() - 3.0
    first_session.update()
    assert first_session.best_time == pytest.approx(3.0, abs=0.05)

    # Simulate restarting the app: a brand-new Game() with no runs yet this
    # session should immediately reflect the prior session's best.
    new_session = Game(history_path=path)
    assert new_session.best_time == pytest.approx(3.0, abs=0.05)


# ── Sound events (game.events) ───────────────────────────────────────────
# A hand-built straight corridor, same technique used in
# tests/progression/test_run.py, so move() is deterministic instead of
# depending on a randomly-generated maze's layout.

CORRIDOR_GRID = [
    [1, 1, 1, 1, 1],
    [1, 0, 0, 0, 1],
    [1, 1, 1, 1, 1],
]


def test_move_into_open_space_appends_the_move_event(game):
    game.grid = [row[:] for row in CORRIDOR_GRID]
    game.player = (1, 1)
    game.goal = (3, 1)
    game.move((1, 0))
    assert game.player == (3, 1)
    assert game.events == ["move"]


def test_move_into_a_wall_appends_no_event(game):
    game.grid = [row[:] for row in CORRIDOR_GRID]
    game.player = (1, 1)
    game.goal = (3, 1)
    game.move((0, -1))  # straight into the border wall
    assert game.player == (1, 1)
    assert game.events == []


def test_reaching_goal_appends_the_maze_complete_event(game):
    game.player = game.goal
    game.update()
    assert game.events == ["maze_complete"]


def test_finishing_does_not_reappend_the_maze_complete_event(game):
    game.player = game.goal
    game.update()
    game.events.clear()  # simulate the loop layer draining events, same as progression/app.py
    game.update()  # already finished -- should be a no-op, no event re-appended
    assert game.events == []


def test_new_maze_does_not_clear_events(game):
    """events is a per-frame buffer drained by the loop layer, not round state -- new_maze() must not touch it."""
    game.grid = [row[:] for row in CORRIDOR_GRID]
    game.player = (1, 1)
    game.goal = (3, 1)
    game.move((1, 0))
    assert game.events == ["move"]
    game.new_maze()
    assert game.events == ["move"]


# ── Adjustable dimensions ────────────────────────────────────────────────


def test_set_dimensions_regenerates_maze(game):
    old_grid = game.grid
    game.set_dimensions(31, 31)
    assert game.cols == 31 and game.rows == 31
    assert len(game.grid) == 31 and len(game.grid[0]) == 31
    assert game.grid != old_grid
    assert game.player == START_POS
    assert game.finished is False


def test_set_dimensions_clamps_to_bounds(game):
    game.set_dimensions(MIN_DIMENSION - 50, MAX_DIMENSION + 50)
    assert game.cols == MIN_DIMENSION
    assert game.rows == MAX_DIMENSION


def test_set_dimensions_forces_odd(game):
    game.set_dimensions(20, 30)  # even inputs
    assert game.cols % 2 == 1
    assert game.rows % 2 == 1


def test_adjust_cols_and_rows_step_by_dimension_step(game):
    from maze_game.constants import DIMENSION_STEP

    start_cols, start_rows = game.cols, game.rows
    game.adjust_cols(1)
    assert game.cols == start_cols + DIMENSION_STEP
    game.adjust_rows(-1)
    assert game.rows == start_rows - DIMENSION_STEP


def test_adjust_cols_does_not_overshoot_max(game):
    for _ in range(100):
        game.adjust_cols(1)
    assert game.cols == MAX_DIMENSION


# ── Run history ───────────────────────────────────────────────────────────


def test_finishing_a_run_appends_a_history_record(game):
    assert game.history == []
    game.player = game.goal
    game.update()
    assert len(game.history) == 1
    record = game.history[0]
    assert record.cols == game.cols
    assert record.rows == game.rows
    assert record.seconds == game.elapsed


def test_history_persists_to_disk_and_reloads(tmp_path):
    path = tmp_path / "history.json"
    game = Game(history_path=path)
    game.player = game.goal
    game.update()

    reloaded = Game(history_path=path)
    assert len(reloaded.history) == 1
    assert reloaded.history[0].cols == game.cols


def test_history_survives_across_new_maze(game):
    game.player = game.goal
    game.update()
    game.new_maze()
    assert len(game.history) == 1


def test_finishing_does_not_double_record_while_still_finished(game):
    game.player = game.goal
    game.update()
    game.update()  # finished is already True; should be a no-op
    assert len(game.history) == 1
