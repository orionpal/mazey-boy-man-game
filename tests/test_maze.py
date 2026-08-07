"""
Tests for maze_game.maze — generation correctness, connectivity, and
scalability (no reliance on Python's recursion limit).
"""

import random
import statistics

import pytest

from maze_game.maze import (
    generate_maze, farthest_reachable_cell, shortest_path, braid,
    _open_neighbour_count, is_stoppable_cell, bfs_reachable, secondary_goal_candidate,
)
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
    """BFS reachability set from `start`. Thin wrapper over the real public bfs_reachable()."""
    return bfs_reachable(grid, start)


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


def test_farthest_reachable_cell_extra_edges_can_reach_an_otherwise_isolated_region():
    """
    A teleporter-shaped shortcut (extra_edges) can make a region plain grid
    adjacency alone would never reach *become* reachable, including cells
    further beyond the shortcut's own endpoint -- this is the mechanism
    augments/__init__.py's _finalize_goal() relies on to account for
    decorative teleporters instead of being blind to them.
    """
    # (1, 1) is fully isolated by walls -- the only way anywhere else is
    # the extra edge. Column 7 is a separate 3-cell vertical dead-end
    # corridor, (7, 1)-(7, 2)-(7, 3), entirely disconnected by grid walls.
    grid = [
        [1, 1, 1, 1, 1, 1, 1, 1, 1],
        [1, 0, 1, 1, 1, 1, 1, 0, 1],
        [1, 1, 1, 1, 1, 1, 1, 0, 1],
        [1, 1, 1, 1, 1, 1, 1, 0, 1],
        [1, 1, 1, 1, 1, 1, 1, 1, 1],
    ]
    start = (1, 1)
    assert farthest_reachable_cell(grid, start) == start  # nothing else is grid-reachable at all

    goal = farthest_reachable_cell(grid, start, extra_edges={start: (7, 1)})
    assert goal == (7, 3)  # walked from the shortcut's own endpoint further down to the real dead end


def test_farthest_reachable_cell_candidates_restricts_which_cell_can_be_the_answer():
    """
    `candidates`, when given, further restricts (on top of the existing
    stoppable-cell rule) which visited cell can be picked as the final
    "farthest" answer -- it does not restrict *traversal*, so a cell
    outside `candidates` is still walked through on the way to one that is
    in it. Used by _finalize_goal() to confine goal placement to cells
    behind an augment's mandatory chain without breaking the BFS itself.
    """
    # A horizontal corridor (1,1)-(7,1) with a short dead-end branch
    # hanging off its junction at (4,1)-(4,2)-(4,3). The branch's own dead
    # end (4,3) is closer to start than the corridor's own dead end (7,1).
    grid = [
        [1, 1, 1, 1, 1, 1, 1, 1, 1],
        [1, 0, 0, 0, 0, 0, 0, 0, 1],
        [1, 1, 1, 1, 0, 1, 1, 1, 1],
        [1, 1, 1, 1, 0, 1, 1, 1, 1],
        [1, 1, 1, 1, 1, 1, 1, 1, 1],
    ]
    start = (1, 1)
    assert farthest_reachable_cell(grid, start) == (7, 1)  # the globally farthest stoppable cell

    restricted = farthest_reachable_cell(grid, start, candidates={(4, 3)})
    assert restricted == (4, 3)  # the branch's own dead end, even though it's the nearer of the two

    # An empty/nonexistent candidates set is treated the same as no restriction at all when falsy.
    assert farthest_reachable_cell(grid, start, candidates=None) == (7, 1)


# ── secondary_goal_candidate (Twin Goals) ─────────────────────────────────


def test_secondary_goal_candidate_returns_a_stoppable_cell_far_from_both_anchors():
    for seed in range(5):
        rng = random.Random(seed)
        grid = generate_maze(21, 21, rng=rng)
        start = (1, 1)
        primary_goal = farthest_reachable_cell(grid, start)
        result = secondary_goal_candidate(grid, start, primary_goal, rng=rng)
        assert result is not None
        assert is_stoppable_cell(grid, *result)
        assert result != start
        assert result != primary_goal


def test_secondary_goal_candidate_respects_exclude():
    rng = random.Random(3)
    grid = generate_maze(21, 21, rng=rng)
    start = (1, 1)
    primary_goal = farthest_reachable_cell(grid, start)
    first = secondary_goal_candidate(grid, start, primary_goal, rng=random.Random(3))
    assert first is not None
    result = secondary_goal_candidate(grid, start, primary_goal, exclude={first}, rng=random.Random(3))
    assert result != first  # excluded cell never re-chosen, even with the same rng draw sequence


def test_secondary_goal_candidate_returns_none_gracefully_when_no_candidate_qualifies():
    # A tiny maze with unreasonably strict thresholds -- nothing can be
    # "far enough" from both anchors at once.
    grid = generate_maze(9, 9, rng=random.Random(1))
    start = (1, 1)
    primary_goal = farthest_reachable_cell(grid, start)
    result = secondary_goal_candidate(
        grid, start, primary_goal, min_start_fraction=0.99, min_goal_fraction=0.99, rng=random.Random(1),
    )
    assert result is None


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


# ── Seeded RNG (instance-threaded rng kwarg) ─────────────────────────────


def test_generate_maze_with_explicit_rng_is_deterministic():
    a = generate_maze(21, 21, rng=random.Random(1234))
    b = generate_maze(21, 21, rng=random.Random(1234))
    assert a == b


def test_generate_maze_with_explicit_rng_does_not_perturb_global_random_state():
    random.seed(555)
    state_before = random.getstate()
    generate_maze(21, 21, rng=random.Random(1))
    assert random.getstate() == state_before


def test_braid_with_explicit_rng_is_deterministic():
    base = generate_maze(21, 21, braid_prob=0.0)
    a = braid(base, p=1.0, rng=random.Random(7))
    b = braid(base, p=1.0, rng=random.Random(7))
    assert a == b


# ── is_stoppable_cell / bfs_reachable ─────────────────────────────────────


def test_is_stoppable_cell_matches_farthest_reachable_cells_rule():
    random.seed(2)
    grid = generate_maze(21, 21)
    for x, y in _open_cells(grid):
        assert is_stoppable_cell(grid, x, y) == (_open_neighbour_count(grid, x, y) != 2)


def test_bfs_reachable_matches_full_connectivity_on_a_perfect_maze():
    random.seed(2)
    grid = generate_maze(21, 21)
    assert bfs_reachable(grid, (1, 1)) == set(_open_cells(grid))


# ── shortest_path extra_edges ─────────────────────────────────────────────


def test_shortest_path_uses_extra_edges_to_reach_an_otherwise_unreachable_cell():
    # Two disconnected 1-cell rooms, only linked by an extra "teleporter" edge.
    grid = [
        [1, 1, 1, 1, 1],
        [1, 0, 1, 0, 1],
        [1, 1, 1, 1, 1],
    ]
    start, goal = (1, 1), (3, 1)
    assert bfs_reachable(grid, start) == {start}  # confirm goal is NOT reachable via grid adjacency alone

    path = shortest_path(grid, start, goal, extra_edges={start: goal})
    assert path == [start, goal]


def test_shortest_path_without_extra_edges_is_unchanged():
    random.seed(4)
    grid = generate_maze(21, 21)
    goal = farthest_reachable_cell(grid, (1, 1))
    assert shortest_path(grid, (1, 1), goal) == shortest_path(grid, (1, 1), goal, extra_edges=None)
