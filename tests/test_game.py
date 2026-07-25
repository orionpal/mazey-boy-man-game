"""
Tests for maze_game.game.Game -- timer behaviour, win condition, and
post-finish freezing (start/end + timer, per the controls audit).
"""

import time

from maze_game.game import Game, START_POS


def test_new_maze_resets_state():
    game = Game()
    assert game.player == START_POS
    assert game.finished is False
    assert game.elapsed == 0.0
    assert game.goal != START_POS


def test_update_advances_elapsed_time():
    game = Game()
    time.sleep(0.05)
    game.update()
    assert game.elapsed > 0.0


def test_reaching_goal_finishes_and_records_best_time():
    game = Game()
    game.player = game.goal  # simulate arriving at the goal
    game.update()
    assert game.finished is True
    assert game.best_time is not None
    assert game.best_time == game.elapsed


def test_timer_freezes_after_finish():
    game = Game()
    game.player = game.goal
    game.update()
    finished_elapsed = game.elapsed
    time.sleep(0.05)
    game.update()
    assert game.elapsed == finished_elapsed


def test_move_is_a_no_op_after_finish():
    game = Game()
    game.player = game.goal
    game.update()
    pos_before = game.player
    game.move((1, 0))
    assert game.player == pos_before


def test_best_time_only_improves():
    game = Game()
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


def test_best_time_persists_across_new_maze():
    game = Game()
    game.player = game.goal
    game.update()
    best = game.best_time
    game.new_maze()
    assert game.best_time == best
    assert game.finished is False
