"""
Tests for maze_game.player.slide — the core "quick, stops-at-junctions"
movement feel the game is built around.
"""

import random

import pytest

from maze_game.maze import generate_maze
from maze_game.player import slide, _open_neighbour_count

DIRECTIONS = [(0, -1), (0, 1), (-1, 0), (1, 0)]


def _open_cells(grid):
    return [
        (x, y)
        for y, row in enumerate(grid)
        for x, val in enumerate(row)
        if val == 0
    ]


@pytest.fixture(params=[21, 35])
def grid(request):
    random.seed(42)
    return generate_maze(request.param, request.param)


def test_slide_never_lands_on_a_wall(grid):
    for start in _open_cells(grid):
        for direction in DIRECTIONS:
            end = slide(grid, start, direction)
            assert grid[end[1]][end[0]] == 0, f"{start} + {direction} -> {end} is a wall"


def test_slide_never_leaves_bounds(grid):
    cols, rows = len(grid[0]), len(grid)
    for start in _open_cells(grid):
        for direction in DIRECTIONS:
            end = slide(grid, start, direction)
            assert 0 <= end[0] < cols and 0 <= end[1] < rows


def test_slide_into_immediate_wall_is_a_no_op(grid):
    """If the very next cell in `direction` is a wall, position must not change."""
    cols, rows = len(grid[0]), len(grid)
    for start in _open_cells(grid):
        for dx, dy in DIRECTIONS:
            nx, ny = start[0] + dx, start[1] + dy
            blocked = not (0 <= nx < cols and 0 <= ny < rows) or grid[ny][nx] == 1
            if blocked:
                assert slide(grid, start, (dx, dy)) == start


def test_slide_stops_only_at_wall_or_junction(grid):
    """
    Every stopping point must be explained by one of:
      - the next cell in `direction` is a wall / out of bounds, or
      - the stopping cell itself is a junction (3+ open neighbours).
    This is the crux of "never gets stuck in a weird spot".
    """
    cols, rows = len(grid[0]), len(grid)
    for start in _open_cells(grid):
        for direction in DIRECTIONS:
            end = slide(grid, start, direction)
            if end == start:
                continue
            ex, ey = end
            dx, dy = direction
            nx, ny = ex + dx, ey + dy
            next_blocked = not (0 <= nx < cols and 0 <= ny < rows) or grid[ny][nx] == 1
            is_junction = _open_neighbour_count(grid, ex, ey) > 2
            assert next_blocked or is_junction, (
                f"stopped at {end} from {start} going {direction} "
                f"without a wall ahead or a junction underfoot"
            )


def test_sliding_again_off_a_wall_stop_does_not_move_further(grid):
    """
    If the first slide stopped because a wall/bound was ahead (a "hard"
    stop, e.g. a dead end), pressing the same direction again must be a
    no-op.

    This is deliberately NOT asserted for junction stops: at a junction with
    the current direction still open, pressing the same arrow again is
    expected to carry the player straight through (that's the intended
    "keep going" behaviour, not a bug) -- see docs/controls-audit.md.
    """
    cols, rows = len(grid[0]), len(grid)
    for start in _open_cells(grid):
        for direction in DIRECTIONS:
            once = slide(grid, start, direction)
            dx, dy = direction
            ox, oy = once
            nx, ny = ox + dx, oy + dy
            wall_ahead = not (0 <= nx < cols and 0 <= ny < rows) or grid[ny][nx] == 1
            if not wall_ahead:
                continue  # this was a junction stop with the direction still open; skip
            twice = slide(grid, once, direction)
            assert once == twice


def test_sliding_again_through_an_open_junction_continues(grid):
    """
    Specifies the intentional counterpart to the wall-stop test above: if a
    stop was a junction stop AND the current direction is still open there,
    pressing the same direction again must move further, not stay put. This
    is what lets the player carry a straight-line combo through a junction
    without needing to "re-confirm" the same key.
    """
    cols, rows = len(grid[0]), len(grid)
    found_a_case = False
    for start in _open_cells(grid):
        for direction in DIRECTIONS:
            once = slide(grid, start, direction)
            dx, dy = direction
            ox, oy = once
            nx, ny = ox + dx, oy + dy
            direction_still_open = (
                0 <= nx < cols and 0 <= ny < rows and grid[ny][nx] == 0
            )
            if not direction_still_open or once == start:
                continue
            found_a_case = True
            twice = slide(grid, once, direction)
            assert twice != once
    assert found_a_case, "fixture maze had no through-junction case to exercise"


def test_round_trip_from_a_resolved_stop_returns_to_the_same_stop():
    """
    From an already-resolved stopping point, sliding backward and then
    forward again must land back on the same stop -- otherwise the same
    two key presses in a row could put the player somewhere different each
    time, which would feel broken.

    Note: this only holds starting from a *resolved* stop. An arbitrary
    open cell picked at random is not necessarily a stopping point (it may
    sit mid-corridor with two in-line open neighbours), so "slide forward
    then immediately back" from an arbitrary cell can legitimately end up
    further back than where you started -- that's correct behaviour, not a
    bug, which is why the property is only asserted from a resolved stop.
    """
    random.seed(7)
    grid = generate_maze(21, 21)
    reverse = {(0, -1): (0, 1), (0, 1): (0, -1), (-1, 0): (1, 0), (1, 0): (-1, 0)}
    for start in _open_cells(grid):
        for direction in DIRECTIONS:
            stop = slide(grid, start, direction)
            if stop == start:
                continue  # blocked immediately; nothing to round-trip
            back = slide(grid, stop, reverse[direction])
            forward_again = slide(grid, back, direction)
            assert forward_again == stop
