"""
Tests for maze_game.game.Game -- timer behaviour, win condition,
post-finish freezing, adjustable dimensions, and run-history recording.
"""

import time

import pytest

from maze_game.constants import MIN_DIMENSION, MAX_DIMENSION
from maze_game.game import Game, START_POS


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
    assert game.finished is False


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
