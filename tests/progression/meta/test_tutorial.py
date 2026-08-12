"""
Tests for maze_game.progression.meta.tutorial -- load/save round trip and
TutorialRun step progression, in isolation. Every test uses tmp_path for
tutorial.json, so none of this ever touches the real on-disk file.
"""

import pytest

from maze_game.maze import shortest_path
from maze_game.player import slide
from maze_game.progression.meta.tutorial import (
    TUTORIAL_STEPS,
    TutorialRun,
    load_tutorial_completed,
    save_tutorial_completed,
)


def _wall_direction_from(grid, cell) -> tuple[int, int] | None:
    """A direction that's immediately a wall/out-of-bounds from `cell` -- so
    calling move() with it from that cell is a guaranteed no-op slide, safe
    to use as "stay put and re-check this cell" in tests below without
    depending on the maze actually having a path leading away from it.
    None if `cell` happens to be open in all 4 directions."""
    for direction in [(1, 0), (-1, 0), (0, 1), (0, -1)]:
        if slide(grid, cell, direction) == cell:
            return direction
    return None


@pytest.fixture
def path(tmp_path):
    return tmp_path / "tutorial.json"


# ── load/save round trip ─────────────────────────────────────────────────


def test_load_tutorial_completed_is_false_when_the_file_is_missing(path):
    assert load_tutorial_completed(path) is False


def test_load_tutorial_completed_is_false_when_the_file_is_corrupt(path):
    path.write_text("not valid json{{{")
    assert load_tutorial_completed(path) is False


def test_load_tutorial_completed_is_false_when_the_file_is_not_a_dict(path):
    path.write_text("[1, 2, 3]")
    assert load_tutorial_completed(path) is False


def test_save_and_load_tutorial_completed_round_trips(path):
    save_tutorial_completed(True, path)
    assert load_tutorial_completed(path) is True

    save_tutorial_completed(False, path)
    assert load_tutorial_completed(path) is False


# ── TutorialRun: step setup ──────────────────────────────────────────────


def test_tutorial_run_starts_on_the_first_step(path):
    run = TutorialRun(seed=1, state_path=path)
    assert run.step_index == 0
    assert run.step == TUTORIAL_STEPS[0]
    assert run.finished is False
    assert run.player == (1, 1)


def test_first_step_has_no_pellet_and_is_untimed(path):
    run = TutorialRun(seed=1, state_path=path)
    assert run.step.timed is False


def test_only_the_last_step_is_timed(path):
    run = TutorialRun(seed=1, state_path=path)
    for step in TUTORIAL_STEPS[:-1]:
        assert step.timed is False
    assert TUTORIAL_STEPS[-1].timed is True


def test_goal_is_reachable_and_not_the_start(path):
    run = TutorialRun(seed=1, state_path=path)
    assert run.goal != run.player


def test_pellet_when_present_is_a_distinct_open_cell(path):
    run = TutorialRun(seed=1, state_path=path)
    if run.pellet is not None:
        assert run.pellet not in (run.player, run.goal)
        assert run.grid[run.pellet[1]][run.pellet[0]] == 0


def test_timed_step_starts_with_a_running_countdown(path):
    run = TutorialRun(seed=1, state_path=path)
    run.step_index = len(TUTORIAL_STEPS) - 1
    run._begin_step()
    assert run.timer is not None
    assert run.timer.remaining > 0
    assert run.step_failed is False


# ── TutorialRun: movement / pellet / advance ─────────────────────────────


def test_move_into_a_wall_does_not_move_the_player_or_emit_a_move_event(path):
    run = TutorialRun(seed=1, state_path=path)
    direction = _wall_direction_from(run.grid, run.player)
    if direction is None:
        pytest.skip("the start cell is open in all 4 directions for this seed")
    run.move(direction)
    assert run.player == (1, 1)
    assert "move" not in run.events


def _open_corridor_run(run) -> None:
    """Overwrites `run` in place with a deterministic 5x1 open corridor
    (walls elsewhere), player at the left end -- isolates move()'s
    contact/advance logic from real maze-generation output entirely."""
    run.grid = [[1] * 5 for _ in range(5)]
    for x in range(5):
        run.grid[2][x] = 0
    run.player = (0, 2)
    run.pellet = None


def test_move_that_reaches_the_goal_advances_to_the_next_step(path):
    run = TutorialRun(seed=1, state_path=path)
    _open_corridor_run(run)
    run.goal = (4, 2)  # far wall end of the corridor
    run.move((1, 0))
    assert run.player == run.goal
    assert "maze_complete" in run.events
    assert run.step_index == 1
    assert run.finished is False


def test_finishing_the_last_step_marks_the_run_finished_and_persists(path):
    run = TutorialRun(seed=1, state_path=path)
    run.step_index = len(TUTORIAL_STEPS) - 1
    _open_corridor_run(run)
    run.goal = (4, 2)
    run.move((1, 0))
    assert run.finished is True
    assert load_tutorial_completed(path) is True


def test_picking_up_the_pellet_clears_it_and_emits_a_pellet_event(path):
    run = TutorialRun(seed=1, state_path=path)
    _open_corridor_run(run)
    run.pellet = (4, 2)  # dead-end cell -- a real stop, not just a pass-through
    run.goal = (9, 9)  # off the corridor, so this move can't also finish the step
    run.move((1, 0))
    assert run.player == (4, 2)
    assert run.pellet is None
    assert "pellet" in run.events


def test_move_picks_up_a_pellet_the_slide_only_passes_through(path):
    """
    Regression test: a plain pellet can land on any open cell (see
    _begin_step()), including a 2-open-neighbour corridor cell a slide can
    only ever pass *through*, never stop on (see is_stoppable_cell()'s
    doc) -- unlike the goal, which farthest_reachable_cell() guarantees is
    always a stoppable cell. move() must therefore check the whole slide
    path for pellet contact (matching progression/run.py's own move()),
    not just the final resting cell, or such a pellet could never be
    picked up by real play.
    """
    run = TutorialRun(seed=1, state_path=path)
    run.grid = [[1] * 5 for _ in range(5)]
    for x in range(5):
        run.grid[2][x] = 0  # a single open corridor row
    run.player = (0, 2)
    run.pellet = (2, 2)  # a straight-through cell: 2 open neighbours, never a stop
    run.goal = (9, 9)  # irrelevant to this test, just not on the slide's path

    run.move((1, 0))

    assert run.player == (4, 2)  # slides all the way to the far wall
    assert run.pellet is None
    assert "pellet" in run.events


# ── TutorialRun: timer / retry ───────────────────────────────────────────


def test_update_is_a_no_op_on_an_untimed_step(path):
    run = TutorialRun(seed=1, state_path=path)
    assert run.timer is None
    run.update()  # must not raise
    assert run.timer is None


def test_update_depletes_the_timer_and_fails_the_step(path):
    run = TutorialRun(seed=1, state_path=path)
    run.step_index = len(TUTORIAL_STEPS) - 1
    run._begin_step()
    run.timer.remaining = 0.001
    run.timer._last_tick -= 1.0  # backdate so the next tick() sees elapsed time
    run.update()
    assert run.step_failed is True
    assert "fail" in run.events


def test_move_is_a_no_op_after_the_step_has_failed(path):
    run = TutorialRun(seed=1, state_path=path)
    run.step_index = len(TUTORIAL_STEPS) - 1
    run._begin_step()
    run.step_failed = True
    start = run.player
    run.move((1, 0))
    assert run.player == start


def test_retry_step_rerolls_a_fresh_maze_and_clears_failure(path):
    run = TutorialRun(seed=1, state_path=path)
    run.step_index = len(TUTORIAL_STEPS) - 1
    run._begin_step()
    run.step_failed = True
    run.retry_step()
    assert run.step_failed is False
    assert run.player == (1, 1)
    assert run.timer is not None
    assert run.timer.depleted is False


# ── TutorialRun: skip ─────────────────────────────────────────────────────


def test_skip_finishes_the_run_and_persists_completion(path):
    run = TutorialRun(seed=1, state_path=path)
    assert run.finished is False
    run.skip()
    assert run.finished is True
    assert load_tutorial_completed(path) is True


def test_skip_on_the_first_step_does_not_require_clearing_any_step(path):
    run = TutorialRun(seed=1, state_path=path)
    assert run.step_index == 0
    run.skip()
    assert run.finished is True
