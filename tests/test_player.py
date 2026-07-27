"""
Tests for maze_game.player.slide — the core "quick, stops-at-junctions"
movement feel the game is built around.
"""

import random

import pytest

from maze_game.maze import generate_maze
from maze_game.player import slide, slide_path, _open_neighbour_count

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


# ── slide_path ────────────────────────────────────────────────────────────


def test_slide_path_last_cell_matches_slide(grid):
    for start in _open_cells(grid):
        for direction in DIRECTIONS:
            path = slide_path(grid, start, direction)
            end = slide(grid, start, direction)
            if path:
                assert path[-1] == end
            else:
                assert end == start


def test_slide_path_is_empty_for_a_no_op_slide(grid):
    cols, rows = len(grid[0]), len(grid)
    for start in _open_cells(grid):
        for dx, dy in DIRECTIONS:
            nx, ny = start[0] + dx, start[1] + dy
            blocked = not (0 <= nx < cols and 0 <= ny < rows) or grid[ny][nx] == 1
            if blocked:
                assert slide_path(grid, start, (dx, dy)) == []


def test_slide_path_never_includes_the_starting_cell_or_a_wall(grid):
    for start in _open_cells(grid):
        for direction in DIRECTIONS:
            path = slide_path(grid, start, direction)
            assert start not in path
            for cx, cy in path:
                assert grid[cy][cx] == 0


def test_slide_path_cells_are_contiguous_steps_in_direction(grid):
    """Every cell in the path is exactly one step from the previous one (or from `start` for the first), in `direction`."""
    dx_dy = {d: d for d in DIRECTIONS}
    for start in _open_cells(grid):
        for direction in DIRECTIONS:
            path = slide_path(grid, start, direction)
            prev = start
            for cell in path:
                assert (cell[0] - prev[0], cell[1] - prev[1]) == dx_dy[direction]
                prev = cell


# ── slide_path(junction_stop_count=...) -- combo moves ────────────────────
# A straight corridor at y=2 with three junctions in a row (branch openings
# at x=3, 5, 7), used to test skipping through a known number of them.

JUNCTION_CHAIN_GRID = [[1] * 11 for _ in range(5)]
for _x in range(1, 10):
    JUNCTION_CHAIN_GRID[2][_x] = 0
JUNCTION_CHAIN_GRID[1][3] = 0
JUNCTION_CHAIN_GRID[1][5] = 0
JUNCTION_CHAIN_GRID[1][7] = 0


def test_junction_stop_count_default_matches_plain_slide_path():
    assert slide_path(JUNCTION_CHAIN_GRID, (1, 2), (1, 0)) == slide_path(
        JUNCTION_CHAIN_GRID, (1, 2), (1, 0), junction_stop_count=1
    )
    assert slide_path(JUNCTION_CHAIN_GRID, (1, 2), (1, 0)) == [(2, 2), (3, 2)]  # stops at the 1st junction


def test_junction_stop_count_n_skips_through_n_minus_1_junctions():
    assert slide_path(JUNCTION_CHAIN_GRID, (1, 2), (1, 0), junction_stop_count=2) == [
        (2, 2), (3, 2), (4, 2), (5, 2),
    ]  # passes the 1st junction, stops at the 2nd
    assert slide_path(JUNCTION_CHAIN_GRID, (1, 2), (1, 0), junction_stop_count=3) == [
        (2, 2), (3, 2), (4, 2), (5, 2), (6, 2), (7, 2),
    ]  # passes the 1st and 2nd, stops at the 3rd


def test_junction_stop_count_none_ignores_junctions_and_stops_only_at_a_wall():
    path = slide_path(JUNCTION_CHAIN_GRID, (1, 2), (1, 0), junction_stop_count=None)
    assert path == [(2, 2), (3, 2), (4, 2), (5, 2), (6, 2), (7, 2), (8, 2), (9, 2)]  # runs to the dead end


def test_junction_stop_count_larger_than_junctions_present_runs_to_the_wall():
    """Asking to skip more junctions than the corridor has just runs it out, same as junction_stop_count=None."""
    assert slide_path(JUNCTION_CHAIN_GRID, (1, 2), (1, 0), junction_stop_count=100) == slide_path(
        JUNCTION_CHAIN_GRID, (1, 2), (1, 0), junction_stop_count=None
    )


# ── slide_path(break_wall=...) -- wall-breaker combo ──────────────────────
# A short corridor with two interior walls in a row (at x=2 and x=4) and a
# border wall at x=6, used to test the break_wall override hook.

BREAKABLE_WALL_GRID = [
    [1, 1, 1, 1, 1, 1, 1],
    [1, 0, 1, 0, 1, 0, 1],
    [1, 1, 1, 1, 1, 1, 1],
]


def test_break_wall_none_behaves_like_a_normal_wall_stop():
    assert slide_path(BREAKABLE_WALL_GRID, (1, 1), (1, 0)) == []  # (2,1) is a wall, no-op


def test_break_wall_returning_true_opens_the_wall_and_continues():
    """An always-True break_wall has no concept of "border" -- that policy belongs to the caller
    (see test_break_wall_can_refuse_partway_through for how a caller enforces it); left unchecked,
    it just keeps breaking through every wall until it runs out of grid entirely."""
    grid = [row[:] for row in BREAKABLE_WALL_GRID]
    path = slide_path(grid, (1, 1), (1, 0), junction_stop_count=None, break_wall=lambda x, y: (grid[y].__setitem__(x, 0), True)[1])
    assert path == [(2, 1), (3, 1), (4, 1), (5, 1), (6, 1)]  # breaks through x=2, x=4, and even the x=6 border
    assert grid[1][2] == 0 and grid[1][4] == 0 and grid[1][6] == 0  # actually mutated


def test_break_wall_returning_false_behaves_like_no_break_wall_at_all():
    path = slide_path(BREAKABLE_WALL_GRID, (1, 1), (1, 0), junction_stop_count=None, break_wall=lambda x, y: False)
    assert path == []


def test_break_wall_can_refuse_partway_through():
    """First wall (x=2) is broken, second (x=4) is refused (e.g. out of charges) -- stops there, x=4 never opened."""
    grid = [row[:] for row in BREAKABLE_WALL_GRID]
    calls = []

    def break_wall(x, y):
        calls.append((x, y))
        if len(calls) == 1:
            grid[y][x] = 0
            return True
        return False

    path = slide_path(grid, (1, 1), (1, 0), junction_stop_count=None, break_wall=break_wall)
    assert path == [(2, 1), (3, 1)]
    assert calls == [(2, 1), (4, 1)]
    assert grid[1][4] == 1  # never opened


def test_break_wall_is_never_called_for_out_of_bounds():
    grid = [[0, 0, 0]]  # 1x3, fully open, no walls at all
    calls = []
    path = slide_path(grid, (2, 0), (1, 0), break_wall=lambda x, y: calls.append((x, y)) or True)
    assert path == []  # (3,0) is out of bounds, not a wall -- nothing to offer break_wall
    assert calls == []


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
