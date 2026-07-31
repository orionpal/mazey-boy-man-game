"""
Tests for maze_game.progression.augments.teleporters -- the first maze
augment. Covers the core "unsolvable without a teleporter" guarantee,
level-scaling formulas, placement invariants (stoppable, non-overlapping,
no fragmentation of the rest of the maze), determinism under a seeded rng,
and end-to-end solvability via the real player.slide()/move() machinery.
"""

from collections import deque

import pytest

from maze_game.constants import (
    TELEPORT_PAIR_COUNT_BASE, TELEPORT_PAIR_COUNT_STEP, TELEPORT_PAIR_COUNT_MAX,
    TELEPORT_MANDATORY_COUNT_BASE, TELEPORT_MANDATORY_COUNT_STEP,
)
from maze_game.maze import generate_maze, farthest_reachable_cell, bfs_reachable, is_stoppable_cell
from maze_game.player import slide_path
from maze_game.progression.augments import AugmentBuild, run_pipeline, ALL_AUGMENTS
from maze_game.progression.augments.teleporters import TeleportersAugment


def _teleporters_augment():
    return next(a for a in ALL_AUGMENTS if a.id == "teleporters")


def _teleport_map(pairs):
    tmap = {}
    for p in pairs:
        tmap[p.a] = p.b
        tmap[p.b] = p.a
    return tmap


def _bfs_reachable_with_teleports(grid, start, tmap):
    """bfs_reachable(), but also hopping through tmap edges -- the "solvable using teleporters" reachability set."""
    seen = set(bfs_reachable(grid, start))
    frontier = list(seen)
    while frontier:
        cell = frontier.pop()
        dest = tmap.get(cell)
        if dest is not None and dest not in seen:
            newly = bfs_reachable(grid, dest) - seen
            seen |= newly
            frontier.extend(newly)
    return seen


def _run_augment_at_level(grid, level, seed_rng):
    start = (1, 1)
    goal = farthest_reachable_cell(grid, start)
    build = AugmentBuild()
    augment = _teleporters_augment()
    for _ in range(level):
        build.acquire(augment)
    return run_pipeline(grid, len(grid[0]), len(grid), start, goal, build, seed_rng)


# ── Core guarantee ────────────────────────────────────────────────────────


def test_goal_is_unreachable_without_a_teleporter_but_reachable_with_one():
    import random
    for seed_val in range(30):
        rng = random.Random(seed_val)
        grid = generate_maze(21, 21, rng=rng)
        ctx = _run_augment_at_level(grid, level=1, seed_rng=rng)
        mandatory = [p for p in ctx.extra["teleporters"] if p.mandatory]
        assert mandatory, f"seed {seed_val}: expected at least one mandatory pair at level 1"

        assert ctx.goal not in bfs_reachable(ctx.grid, (1, 1))

        tmap = _teleport_map(ctx.extra["teleporters"])
        assert ctx.goal in _bfs_reachable_with_teleports(ctx.grid, (1, 1), tmap)


# ── Level-scaling formulas ───────────────────────────────────────────────


@pytest.mark.parametrize("level", [1, 2, 3, 4, 5])
def test_pair_and_mandatory_counts_follow_the_level_formula(level):
    import random
    rng = random.Random(level * 7 + 1)
    grid = generate_maze(21, 21, rng=rng)
    ctx = _run_augment_at_level(grid, level=level, seed_rng=rng)
    pairs = ctx.extra["teleporters"]
    mandatory = [p for p in pairs if p.mandatory]

    expected_pair_count = min(TELEPORT_PAIR_COUNT_BASE + TELEPORT_PAIR_COUNT_STEP * (level - 1), TELEPORT_PAIR_COUNT_MAX)
    expected_mandatory_count = min(
        TELEPORT_MANDATORY_COUNT_BASE + TELEPORT_MANDATORY_COUNT_STEP * (level - 1), expected_pair_count,
    )
    assert len(pairs) == expected_pair_count
    # Mandatory placement can fall short of the formula (graceful
    # degradation on cramped mazes), never exceed it.
    assert len(mandatory) <= expected_mandatory_count


# ── Placement invariants ─────────────────────────────────────────────────


def test_every_teleporter_endpoint_is_a_stoppable_cell():
    import random
    rng = random.Random(11)
    grid = generate_maze(21, 21, rng=rng)
    ctx = _run_augment_at_level(grid, level=3, seed_rng=rng)
    for pair in ctx.extra["teleporters"]:
        assert is_stoppable_cell(ctx.grid, *pair.a)
        assert is_stoppable_cell(ctx.grid, *pair.b)


def test_teleporter_cells_never_overlap_start_goal_or_each_other():
    import random
    rng = random.Random(12)
    grid = generate_maze(21, 21, rng=rng)
    start = (1, 1)
    goal = farthest_reachable_cell(grid, start)
    build = AugmentBuild()
    augment = _teleporters_augment()
    build.acquire(augment)
    build.acquire(augment)
    build.acquire(augment)
    ctx = run_pipeline(grid, 21, 21, start, goal, build, rng)

    all_cells = []
    for pair in ctx.extra["teleporters"]:
        all_cells.extend([pair.a, pair.b])
    assert start not in all_cells
    assert ctx.goal not in all_cells
    assert len(all_cells) == len(set(all_cells))  # no duplicates


def test_main_region_minus_sealed_pockets_stays_fully_connected():
    """
    Regression guard for the pendant-subtree pocket-selection fix: an
    arbitrary connected blob is usually a *bridge* in a near-tree maze, and
    naively sealing one fragments unrelated parts of the maze. Checked
    against the *final* grid's own open-cell set (not the pre-seal one --
    sealing legitimately converts some previously-open boundary wall
    segments into walls, which is the intended effect, not "orphaned"
    space): every cell still open after the augment runs must be reachable
    from start, directly or via a teleporter hop.
    """
    import random
    for seed_val in range(20):
        rng = random.Random(100 + seed_val)
        grid = generate_maze(21, 21, rng=rng)
        start = (1, 1)

        ctx = _run_augment_at_level(grid, level=4, seed_rng=rng)
        tmap = _teleport_map(ctx.extra["teleporters"])
        after = _bfs_reachable_with_teleports(ctx.grid, start, tmap)

        open_cells = {
            (x, y) for y, row in enumerate(ctx.grid) for x, v in enumerate(row) if v == 0
        }
        assert open_cells <= after, f"seed {seed_val}: open cells became unreachable even via teleporters"


def test_decorative_pairs_never_placed_inside_a_sealed_pocket():
    import random
    rng = random.Random(13)
    grid = generate_maze(21, 21, rng=rng)
    ctx = _run_augment_at_level(grid, level=2, seed_rng=rng)
    main_region = bfs_reachable(ctx.grid, (1, 1))
    for pair in ctx.extra["teleporters"]:
        if not pair.mandatory:
            assert pair.a in main_region
            assert pair.b in main_region


# ── Determinism ───────────────────────────────────────────────────────────


def test_same_seed_produces_identical_teleporter_placement():
    import random
    grid = generate_maze(21, 21, rng=random.Random(55))

    ctx_a = _run_augment_at_level([row[:] for row in grid], level=3, seed_rng=random.Random(999))
    ctx_b = _run_augment_at_level([row[:] for row in grid], level=3, seed_rng=random.Random(999))

    assert ctx_a.extra["teleporters"] == ctx_b.extra["teleporters"]
    assert ctx_a.grid == ctx_b.grid
    assert ctx_a.goal == ctx_b.goal


# ── player.slide_path teleport callback ──────────────────────────────────

# A straight 5-cell corridor: (1,1)-(2,1)-(3,1)-(4,1)-(5,1).
CORRIDOR_GRID = [
    [1, 1, 1, 1, 1, 1, 1],
    [1, 0, 0, 0, 0, 0, 1],
    [1, 1, 1, 1, 1, 1, 1],
]


def test_slide_path_stops_at_the_linked_cell_when_entering_a_teleporter():
    teleport_map = {(2, 1): (5, 1)}
    path = slide_path(
        CORRIDOR_GRID, (1, 1), (1, 0),
        junction_stop_count=None,
        teleport=lambda x, y: teleport_map.get((x, y)),
    )
    # Slides from (1,1) rightwards: enters (2,1), which is a teleporter --
    # warps immediately to (5,1) and stops (one hop, no momentum carried through).
    assert path == [(2, 1), (5, 1)]


def test_slide_path_teleport_is_a_noop_when_no_cell_is_linked():
    path = slide_path(CORRIDOR_GRID, (1, 1), (1, 0), junction_stop_count=None, teleport=lambda x, y: None)
    assert path == [(2, 1), (3, 1), (4, 1), (5, 1)]  # runs to the wall, same as with no teleport at all


def test_slide_path_teleport_composes_with_break_wall():
    # A 1-wide corridor with a wall between (2,1) and (3,1) that break_wall opens;
    # (3,1) is a teleporter linked to (5,1).
    grid = [row[:] for row in CORRIDOR_GRID]
    grid[1][3] = 1  # wall between cell (2,1) and (4,1) at the (3,1) midpoint... use as a break target directly
    broken = []

    def break_wall(nx, ny):
        broken.append((nx, ny))
        grid[ny][nx] = 0
        return True

    teleport_map = {(3, 1): (5, 1)}
    path = slide_path(
        grid, (1, 1), (1, 0),
        junction_stop_count=None,
        break_wall=break_wall,
        teleport=lambda x, y: teleport_map.get((x, y)),
    )
    assert (3, 1) in broken
    assert path[-1] == (5, 1)


# ── End-to-end solvability ────────────────────────────────────────────────


DIRECTIONS = [(0, -1), (0, 1), (-1, 0), (1, 0)]


def _goal_reachable_via_real_moves(grid, start, goal, tmap) -> bool:
    """
    BFS over the *real* game-state graph: from each position, the only
    "next positions" are wherever a real player.slide_path() call (with the
    teleport callback wired in, exactly as LabyrinthRun.move() does) in each
    of the 4 directions actually lands. This is the direct, unfoolable proof
    the maze is completable via real play -- unlike following one
    precomputed shortest_path route, it can't be derailed by a *decorative*
    teleporter pad that a greedy route-follower might stumble into
    unintentionally (decorative pads are unconditionally "live": entering
    one always warps, whether or not that was the plan), since it explores
    every real move from every real position, not just one intended route.
    """
    teleport = lambda x, y: tmap.get((x, y))
    seen = {start}
    queue = deque([start])
    while queue:
        pos = queue.popleft()
        if pos == goal:
            return True
        for direction in DIRECTIONS:
            moved = slide_path(grid, pos, direction, teleport=teleport)
            if not moved:
                continue
            new_pos = moved[-1]
            if new_pos not in seen:
                seen.add(new_pos)
                queue.append(new_pos)
    return False


def test_teleporter_gated_maze_is_actually_completable_via_real_slide():
    import random
    for seed_val in range(10):
        rng = random.Random(200 + seed_val)
        grid = generate_maze(21, 21, rng=rng)
        ctx = _run_augment_at_level(grid, level=1, seed_rng=rng)
        tmap = _teleport_map(ctx.extra["teleporters"])

        assert _goal_reachable_via_real_moves(ctx.grid, (1, 1), ctx.goal, tmap), (
            f"seed_val {seed_val}: goal not reachable via any sequence of real moves"
        )


def test_teleporter_gated_maze_is_completable_across_sizes_and_levels():
    """
    Regression guard for a real bug found via this exact check: a decorative
    pad placed at a stoppable cell that happens to be load-bearing for
    reaching some other part of the maze forces an unconditional redirect
    the instant it's entered, silently making the maze unsolvable even
    though plain grid-adjacency reachability (bfs_reachable, or
    shortest_path's extra_edges, which both treat a teleporter as an
    *optional* extra edge rather than a forced one) sees nothing wrong.
    Only ever showed up on small (9x9) mazes in practice -- larger ones have
    enough alternate routes/braid loops that a single bad pad rarely matters
    -- but MIN_DIMENSION is 9, so it's a real, reachable case, not a
    theoretical one.
    """
    import random
    failures = []
    for size in (9, 21, 41):
        for level in (1, 3, 5):
            for seed_val in range(15):
                rng = random.Random(seed_val * 777 + size * 13 + level)
                grid = generate_maze(size, size, rng=rng)
                ctx = _run_augment_at_level(grid, level=level, seed_rng=rng)
                tmap = _teleport_map(ctx.extra["teleporters"])
                if not _goal_reachable_via_real_moves(ctx.grid, (1, 1), ctx.goal, tmap):
                    failures.append((size, level, seed_val))
    assert not failures, f"unsolvable combinations: {failures}"
