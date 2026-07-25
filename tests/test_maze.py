"""
Tests for maze_game.maze — generation correctness, connectivity, and
scalability (no reliance on Python's recursion limit).
"""

import random
import statistics

import pytest

from maze_game.maze import generate_maze, farthest_reachable_cell, shortest_path, braid, _open_neighbour_count
from maze_game.player import slide

SIZES = [5, 9, 21, 51]


def _open_cells(grid):
    return [
        (x, y)
        for y, row in enumerate(grid)
        for x, val in enumerate(row)
        if val == 0
    ]


def _reachable_from(grid, start):
    """BFS reachability set from `start` (mirrors farthest_reachable_cell's traversal)."""
    from collections import deque

    cols, rows = len(grid[0]), len(grid)
    seen = {start}
    q = deque([start])
    while q:
        cx, cy = q.popleft()
        for dx, dy in ((0, 1), (0, -1), (1, 0), (-1, 0)):
            nx, ny = cx + dx, cy + dy
            if (
                0 <= nx < cols
                and 0 <= ny < rows
                and grid[ny][nx] == 0
                and (nx, ny) not in seen
            ):
                seen.add((nx, ny))
                q.append((nx, ny))
    return seen


@pytest.mark.parametrize("size", SIZES)
def test_generate_maze_shape(size):
    grid = generate_maze(size, size)
    assert len(grid) == size
    assert all(len(row) == size for row in grid)


@pytest.mark.parametrize("size", SIZES)
def test_generate_maze_is_binary(size):
    grid = generate_maze(size, size)
    values = {val for row in grid for val in row}
    assert values <= {0, 1}


def test_generate_maze_rejects_even_dimensions():
    with pytest.raises(ValueError):
        generate_maze(20, 21)
    with pytest.raises(ValueError):
        generate_maze(21, 20)


@pytest.mark.parametrize("size", SIZES)
def test_generate_maze_is_fully_connected(size):
    """
    A 'perfect maze' (recursive backtracker) must connect every open cell
    reachable from the carve origin. This is the property the game relies
    on to guarantee the goal is always reachable.
    """
    grid = generate_maze(size, size)
    open_cells = set(_open_cells(grid))
    reachable = _reachable_from(grid, (1, 1))
    assert reachable == open_cells


@pytest.mark.parametrize("size", SIZES)
def test_generate_maze_has_no_2x2_open_blocks(size):
    """
    A 'perfect maze' should have no open rooms/loops -- every 2x2 block of
    cells should contain at least one wall. This is what gives the maze its
    corridor-like, no-loops structure (a spanning tree, not a general graph).
    """
    grid = generate_maze(size, size)
    for y in range(size - 1):
        for x in range(size - 1):
            block = (grid[y][x], grid[y][x + 1], grid[y + 1][x], grid[y + 1][x + 1])
            assert block != (0, 0, 0, 0), f"open 2x2 block at ({x},{y})"


def test_generate_maze_deterministic_with_seeded_random():
    random.seed(1234)
    a = generate_maze(21, 21)
    random.seed(1234)
    b = generate_maze(21, 21)
    assert a == b


@pytest.mark.parametrize("size", [51, 101, 151, 201])
def test_generate_maze_scales_past_recursion_limit(size):
    """
    Regression test: the original recursive-backtracker implementation used
    Python function-call recursion to carve, which raised RecursionError for
    grids around 101x101 and larger (roughly >~500 open cells with the
    default sys.getrecursionlimit()). Generation must not depend on Python's
    call stack depth, however large the grid.
    """
    grid = generate_maze(size, size)
    assert len(grid) == size


def test_farthest_reachable_cell_is_open_and_far():
    grid = generate_maze(21, 21)
    start = (1, 1)
    goal = farthest_reachable_cell(grid, start)
    assert grid[goal[1]][goal[0]] == 0
    assert goal != start


def test_farthest_reachable_cell_is_the_farthest_among_valid_stopping_points():
    """
    farthest_reachable_cell must match a from-scratch BFS distance
    computation -- but only among cells the sliding mechanic can actually
    stop on (dead ends and junctions), not the absolute farthest cell
    overall. A plain "farthest cell, period" can land on a 2-open-neighbour
    mid-corridor cell, which player.slide() can never stop on (it only
    stops at a wall ahead or a junction) -- that made the maze unsolvable
    whenever it happened (~18% of generated mazes, confirmed empirically,
    before this was fixed).
    """
    from collections import deque

    grid = generate_maze(21, 21)
    start = (1, 1)
    cols, rows = len(grid[0]), len(grid)

    dist = {start: 0}
    q = deque([start])
    while q:
        cx, cy = q.popleft()
        for dx, dy in ((0, 1), (0, -1), (1, 0), (-1, 0)):
            nx, ny = cx + dx, cy + dy
            if (
                0 <= nx < cols
                and 0 <= ny < rows
                and grid[ny][nx] == 0
                and (nx, ny) not in dist
            ):
                dist[(nx, ny)] = dist[(cx, cy)] + 1
                q.append((nx, ny))

    expected_max_among_stopping_points = max(
        d for (x, y), d in dist.items() if _open_neighbour_count(grid, x, y) != 2
    )
    goal = farthest_reachable_cell(grid, start)
    assert _open_neighbour_count(grid, *goal) != 2
    assert dist[goal] == expected_max_among_stopping_points


def _simulate_slide_along_path(grid, path):
    """
    Walk `path` for real via player.slide(), recomputing the direction from
    wherever we *actually* are after each press (not from a precomputed
    direction-change list). This matters because slide() force-stops at any
    junction it enters, even if the path continues straight through without
    turning there -- a precomputed "direction changed" list misses that
    forced stop entirely and undershoots. Recomputing fresh from the real
    landing position each time sidesteps that: whatever slide() returns is
    guaranteed to be a cell on the path (it's the same corridor), so we
    always know the correct next direction to press.
    """
    pos = path[0]
    goal = path[-1]
    idx = 0
    for _ in range(len(path) + 5):  # generous bound; real completion needs far fewer presses than cells
        if pos == goal:
            return pos
        direction = (path[idx + 1][0] - pos[0], path[idx + 1][1] - pos[1])
        pos = slide(grid, pos, direction)
        idx = path.index(pos, idx)
    return pos


@pytest.mark.parametrize("size", [9, 21, 41])
def test_maze_is_actually_completable_via_sliding(size):
    """
    End-to-end regression test for the pass-through-goal bug: derive the
    key-press sequence from the real shortest path (start to goal) and
    actually run it through player.slide(), the same function real input
    goes through -- confirms the player lands exactly on the goal, not
    just that a "path" exists on paper. This is the direct proof the maze
    is completable, and would have caught the original bug immediately (a
    pass-through goal made the final press slide straight past it).
    """
    random.seed(11)
    for _ in range(20):
        grid = generate_maze(size, size)  # default params -- braid included, matches real play
        start = (1, 1)
        goal = farthest_reachable_cell(grid, start)
        path = shortest_path(grid, start, goal)

        final_pos = _simulate_slide_along_path(grid, path)
        assert final_pos == goal


# ── Growing Tree branching-density parameter ─────────────────────────────


def _junction_fraction(grid):
    open_cells = _open_cells(grid)
    junctions = sum(1 for x, y in open_cells if _open_neighbour_count(grid, x, y) >= 3)
    return junctions / len(open_cells)


@pytest.mark.parametrize("newest_prob", [0.0, 0.4, 1.0])
def test_generate_maze_stays_connected_across_newest_prob(newest_prob):
    grid = generate_maze(21, 21, newest_prob=newest_prob, braid_prob=0.0)
    open_cells = set(_open_cells(grid))
    assert _reachable_from(grid, (1, 1)) == open_cells


def test_lower_newest_prob_increases_branching():
    """
    newest_prob=1.0 is exactly the old DFS/recursive-backtracker behaviour
    (long, low-branching corridors); lower values should measurably increase
    junction density on average. Averaged over many trials to avoid flakiness
    from any single maze's randomness.
    """
    random.seed(99)
    trials = 40
    high = [_junction_fraction(generate_maze(21, 21, newest_prob=1.0, braid_prob=0.0)) for _ in range(trials)]
    low = [_junction_fraction(generate_maze(21, 21, newest_prob=0.0, braid_prob=0.0)) for _ in range(trials)]
    assert statistics.mean(low) > statistics.mean(high) * 1.5


def test_default_newest_prob_is_meaningfully_branchier_than_pure_dfs():
    """
    Regression guard for the actual fix here: the shipped default should not
    quietly regress back toward the old ~5%-junction DFS feel.
    """
    random.seed(123)
    trials = 40
    default = [_junction_fraction(generate_maze(21, 21)) for _ in range(trials)]
    pure_dfs = [_junction_fraction(generate_maze(21, 21, newest_prob=1.0, braid_prob=0.0)) for _ in range(trials)]
    assert statistics.mean(default) > statistics.mean(pure_dfs) * 1.5


# ── Braiding ──────────────────────────────────────────────────────────────


def test_braid_reduces_dead_ends():
    random.seed(5)
    grid = generate_maze(21, 21, newest_prob=0.4, braid_prob=0.0)
    open_cells = _open_cells(grid)
    dead_ends_before = sum(1 for x, y in open_cells if _open_neighbour_count(grid, x, y) == 1)

    braided = braid(grid, p=1.0)
    dead_ends_after = sum(1 for x, y in open_cells if _open_neighbour_count(braided, x, y) == 1)

    assert dead_ends_before > 0
    assert dead_ends_after < dead_ends_before


def test_braid_at_p_1_eliminates_nearly_all_dead_ends():
    """
    Not necessarily *all* -- a dead end's only candidate wall can be
    rejected specifically to avoid isolating a wall pillar (see
    test_braid_never_isolates_a_wall_pillar), so a handful can survive even
    at p=1.0. The overwhelming majority should still be eliminated.
    """
    random.seed(5)
    grid = generate_maze(21, 21, newest_prob=0.4, braid_prob=0.0)
    open_cells = _open_cells(grid)
    dead_ends_before = sum(1 for x, y in open_cells if _open_neighbour_count(grid, x, y) == 1)

    braided = braid(grid, p=1.0)
    dead_ends_after = sum(1 for x, y in open_cells if _open_neighbour_count(braided, x, y) == 1)

    assert dead_ends_after < dead_ends_before * 0.1


def test_braid_only_adds_edges_so_connectivity_is_preserved():
    random.seed(5)
    grid = generate_maze(21, 21, newest_prob=0.4, braid_prob=0.0)
    braided = braid(grid, p=1.0)
    open_cells = set(_open_cells(braided))
    assert _reachable_from(braided, (1, 1)) == open_cells


def test_braid_does_not_mutate_input():
    random.seed(5)
    grid = generate_maze(21, 21, newest_prob=0.4, braid_prob=0.0)
    before = [row[:] for row in grid]
    braid(grid, p=1.0)
    assert grid == before


def test_braid_never_opens_the_even_even_wall_intersections():
    """
    Regression guard for the exact bug found while building this: braid()
    originally checked whether the *neighbour cell* was a wall, which is
    never true post-generation (every odd,odd cell is already carved), so
    it silently did nothing. This checks the real invariant instead: the
    even,even grid-intersection points must never be carved, in either the
    base generator or after braiding -- carving one would open a true 2x2
    block, which would break the "no open rooms/loops-outside-the-lattice"
    structure the game's corridor rendering assumes.
    """
    random.seed(5)
    grid = braid(generate_maze(21, 21, newest_prob=0.2, braid_prob=0.0), p=1.0)
    for y in range(0, len(grid), 2):
        for x in range(0, len(grid[0]), 2):
            assert grid[y][x] == 1, f"even,even intersection ({x},{y}) was carved open"


def test_generate_maze_with_braid_has_no_2x2_open_blocks():
    random.seed(5)
    grid = generate_maze(21, 21, newest_prob=0.3, braid_prob=1.0)
    size = 21
    for y in range(size - 1):
        for x in range(size - 1):
            block = (grid[y][x], grid[y][x + 1], grid[y + 1][x], grid[y + 1][x + 1])
            assert block != (0, 0, 0, 0), f"open 2x2 block at ({x},{y})"


def _isolated_wall_pillars(grid):
    """Wall cells (1) fully surrounded by open cells on all 4 sides -- a 1-cell loop around a single wall pixel."""
    cols, rows = len(grid[0]), len(grid)
    found = []
    for y in range(rows):
        for x in range(cols):
            if grid[y][x] != 1:
                continue
            if all(
                0 <= x + dx < cols and 0 <= y + dy < rows and grid[y + dy][x + dx] == 0
                for dx, dy in ((0, 1), (0, -1), (1, 0), (-1, 0))
            ):
                found.append((x, y))
    return found


def test_base_generation_never_produces_an_isolated_wall_pillar():
    """The spanning tree (no braid) has no cycles at all, so this can't happen before braiding."""
    random.seed(1)
    for _ in range(50):
        grid = generate_maze(21, 21, newest_prob=0.4, braid_prob=0.0)
        assert _isolated_wall_pillars(grid) == []


def test_braid_never_isolates_a_wall_pillar():
    """
    Regression test: braid() used to sometimes open a wall segment that
    completed a loop running all the way around a single standalone wall
    cell (found by playtesting -- a "square" path around one wall pixel).
    Root cause: opening any single wall segment can, coincidentally, be the
    4th of the 4 segments surrounding one grid intersection, fully
    surrounding that intersection's wall pixel with open cells. Checked at
    braid_prob=1.0 (worst case -- most wall segments opened) across many
    trials and maze sizes.
    """
    random.seed(3)
    for size in (9, 21, 35):
        for _ in range(30):
            grid = generate_maze(size, size, newest_prob=0.3, braid_prob=1.0)
            assert _isolated_wall_pillars(grid) == [], f"found an isolated pillar at size {size}"
