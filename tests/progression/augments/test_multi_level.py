"""
Tests for maze_game.progression.augments.multi_level -- the third maze
augment. Covers the core "goal unreachable without the stairs" forced-use
guarantee (the same standard teleporters.py/doors.py hold themselves to --
see test_teleporters.py::test_goal_is_unreachable_without_a_teleporter_but_reachable_with_one
and test_doors.py::test_goal_is_unreachable_while_locked_but_reachable_after_collecting_keys),
level-scaling formulas, placement invariants, determinism, and end-to-end
solvability via the real player.slide_path() machinery.
"""

import random

import pytest

from maze_game.constants import (
    MULTI_LEVEL_FLOOR_COUNT_BASE, MULTI_LEVEL_FLOOR_COUNT_STEP, MULTI_LEVEL_FLOOR_COUNT_MAX,
    MULTI_LEVEL_MANDATORY_COUNT_BASE, MULTI_LEVEL_MANDATORY_COUNT_STEP,
)
from maze_game.maze import generate_maze, farthest_reachable_cell, bfs_reachable
from maze_game.progression.augments import AugmentBuild, run_pipeline, ALL_AUGMENTS
from maze_game.progression.augments.doors import sequentially_reachable


def _multi_level_augment():
    return next(a for a in ALL_AUGMENTS if a.id == "multi_level")


def _stairs_map(floors):
    tmap = {}
    for link in floors:
        tmap[link.entrance] = link.floor_start
        tmap[link.floor_exit] = link.return_landing
    return tmap


def _full_teleport_map(ctx):
    tmap = {}
    for pair in ctx.extra.get("teleporters", []):
        tmap[pair.a] = pair.b
        tmap[pair.b] = pair.a
    tmap.update(_stairs_map(ctx.extra.get("floors", [])))
    return tmap


def _run_multi_level_at_level(grid, level, seed_rng):
    start = (1, 1)
    goal = farthest_reachable_cell(grid, start)
    build = AugmentBuild()
    augment = _multi_level_augment()
    for _ in range(level):
        build.acquire(augment)
    return run_pipeline(grid, len(grid[0]), len(grid), start, goal, build, seed_rng)


# ── Core guarantee ────────────────────────────────────────────────────────


def test_goal_is_unreachable_without_stairs_but_reachable_with_them():
    for seed_val in range(30):
        rng = random.Random(seed_val)
        grid = generate_maze(21, 21, rng=rng)
        ctx = _run_multi_level_at_level(grid, level=1, seed_rng=rng)
        mandatory = [f for f in ctx.extra["floors"] if f.mandatory]
        assert mandatory, f"seed {seed_val}: expected at least one mandatory floor at level 1"

        # Plain grid adjacency (no stairs hopping at all) must never reach
        # the goal -- a mandatory floor's pocket is sealed with no kept-open
        # crossing, so the stairs pair is the only way in.
        plain_reachable = bfs_reachable(ctx.grid, (1, 1))
        assert ctx.goal not in plain_reachable, (
            f"seed {seed_val}: goal reachable via plain grid adjacency without using any stairs"
        )

        # Ground-truth real-move simulation, folding in doors' sequential
        # key-unlock order (empty here) and every stairs/teleporter warp,
        # must reach the goal.
        tmap = _full_teleport_map(ctx)
        reachable = sequentially_reachable(
            ctx.grid, (1, 1), ctx.extra.get("doors", []), teleport=lambda x, y: tmap.get((x, y)),
        )
        assert ctx.goal in reachable, (
            f"seed {seed_val}: goal not reachable even after walking every stairs pair"
        )


def test_goal_is_unreachable_skipping_even_one_mandatory_floors_stairs():
    """A stronger version of the core guarantee at higher levels: locking out
    any single mandatory floor's `entrance` (as if the player refused to
    use it) must make the goal unreachable, proving every mandatory floor
    -- not just the deepest one -- sits on the only path to the goal."""
    rng = random.Random(3)
    grid = generate_maze(25, 25, rng=rng)
    ctx = _run_multi_level_at_level(grid, level=3, seed_rng=rng)
    mandatory = [f for f in ctx.extra["floors"] if f.mandatory]
    assert len(mandatory) >= 2, "expected level 3 to place >=2 mandatory floors on this seed"

    full_tmap = _full_teleport_map(ctx)
    for skip in mandatory:
        tmap = dict(full_tmap)
        del tmap[skip.entrance]
        del tmap[skip.floor_exit]
        reachable = sequentially_reachable(
            ctx.grid, (1, 1), ctx.extra.get("doors", []), teleport=lambda x, y: tmap.get((x, y)),
        )
        assert ctx.goal not in reachable, (
            f"goal still reachable while floor {skip.floor}'s stairs "
            f"({skip.entrance}->{skip.floor_start}) are disabled"
        )


# ── Level-scaling formulas ───────────────────────────────────────────────


@pytest.mark.parametrize("level", [1, 2, 3, 4, 5])
def test_floor_and_mandatory_counts_follow_the_level_formula(level):
    rng = random.Random(level * 11 + 3)
    grid = generate_maze(21, 21, rng=rng)
    ctx = _run_multi_level_at_level(grid, level=level, seed_rng=rng)
    floors = ctx.extra["floors"]
    mandatory = [f for f in floors if f.mandatory]

    expected_floor_count = min(
        MULTI_LEVEL_FLOOR_COUNT_BASE + MULTI_LEVEL_FLOOR_COUNT_STEP * (level - 1), MULTI_LEVEL_FLOOR_COUNT_MAX,
    )
    expected_mandatory_count = min(
        MULTI_LEVEL_MANDATORY_COUNT_BASE + MULTI_LEVEL_MANDATORY_COUNT_STEP * (level - 1), expected_floor_count,
    )
    assert len(floors) == expected_floor_count
    # Mandatory placement can fall short of the formula (graceful
    # degradation on cramped mazes), never exceed it.
    assert len(mandatory) <= expected_mandatory_count


# ── Placement invariants ─────────────────────────────────────────────────


def test_stairs_cells_never_overlap_start_goal_or_each_other():
    rng = random.Random(99)
    grid = generate_maze(21, 21, rng=rng)
    ctx = _run_multi_level_at_level(grid, level=3, seed_rng=rng)

    all_cells = []
    for link in ctx.extra["floors"]:
        all_cells.extend([link.entrance, link.floor_start, link.floor_exit, link.return_landing])
    assert (1, 1) not in all_cells
    assert ctx.goal not in all_cells
    assert len(all_cells) == len(set(all_cells))  # no duplicates


def test_entrance_and_return_landing_are_distinct_parent_cells():
    """
    The asymmetric-stairs guarantee: a floor's up-marker (entrance) and
    down-marker (return_landing) are both real, distinct, stoppable parent
    cells -- not the same round-trip cell -- and return_landing on its own
    (never having taken floor_exit) has no special effect, matching a
    plain grid cell until the floor's own down-stairs are actually used.
    """
    rng = random.Random(2024)
    grid = generate_maze(21, 21, rng=rng)
    ctx = _run_multi_level_at_level(grid, level=1, seed_rng=rng)
    assert ctx.extra["floors"], "expected at least one floor at level 1"

    for link in ctx.extra["floors"]:
        assert link.entrance != link.return_landing
        assert link.floor_start != link.floor_exit
        tmap = _stairs_map(ctx.extra["floors"])
        # return_landing is only ever a *value* in the map (a destination),
        # never a key -- stepping onto it isn't itself a trigger.
        assert link.return_landing not in tmap


# ── Determinism ───────────────────────────────────────────────────────────


def test_same_seed_produces_identical_floor_placement():
    grid = generate_maze(21, 21, rng=random.Random(55))

    ctx_a = _run_multi_level_at_level([row[:] for row in grid], level=3, seed_rng=random.Random(999))
    ctx_b = _run_multi_level_at_level([row[:] for row in grid], level=3, seed_rng=random.Random(999))

    assert ctx_a.extra["floors"] == ctx_b.extra["floors"]
    assert ctx_a.grid == ctx_b.grid
    assert ctx_a.goal == ctx_b.goal


# ── End-to-end solvability ────────────────────────────────────────────────


def test_multi_level_maze_is_completable_across_sizes_and_levels():
    failures = []
    for size in (9, 21, 41):
        for level in (1, 3, 5):
            for seed_val in range(10):
                rng = random.Random(seed_val * 555 + size * 17 + level)
                grid = generate_maze(size, size, rng=rng)
                ctx = _run_multi_level_at_level(grid, level=level, seed_rng=rng)
                tmap = _full_teleport_map(ctx)
                reachable = sequentially_reachable(
                    ctx.grid, (1, 1), ctx.extra.get("doors", []), teleport=lambda x, y: tmap.get((x, y)),
                )
                if ctx.goal not in reachable:
                    failures.append((size, level, seed_val))
    assert not failures, f"unsolvable combinations: {failures}"


# ── Composition with teleporters and doors (registry-order concern) ──────


def test_multi_level_composes_with_teleporters_and_doors_without_a_bypass():
    """
    All three augments active, run through the real ALL_AUGMENTS pipeline
    (registry order: teleporters, doors, multi_level -- exactly as in
    play). Neither an existing teleporter nor an existing door should let
    the player bypass a mandatory floor's sealed boundary, and vice versa.

    This only checks the goal is reachable with everything intact -- the
    weaker property that did NOT catch the real "last augment to run wins
    ownership of ctx.goal" composability bug (see augments/__init__.py's
    AugmentContext docstring and docs/progression.md's Multi-Level Mazes
    section). test_composition.py's
    test_all_three_augments_together_all_gate_the_goal() is the strengthened
    version of this exact scenario: it additionally proves disabling any
    *one* augment's mandatory content, with the other two left fully
    intact, breaks solvability -- the property that actually would have
    caught that bug.
    """
    from maze_game.progression.augments.doors import DoorsAugment  # noqa: F401 (imported for clarity)
    from maze_game.progression.augments.teleporters import TeleportersAugment  # noqa: F401

    teleporters_augment = next(a for a in ALL_AUGMENTS if a.id == "teleporters")
    doors_augment = next(a for a in ALL_AUGMENTS if a.id == "doors")
    multi_level_augment = _multi_level_augment()

    failures = []
    for seed_val in range(15):
        rng = random.Random(700 + seed_val)
        grid = generate_maze(25, 25, rng=rng)
        start = (1, 1)
        goal = farthest_reachable_cell(grid, start)
        build = AugmentBuild()
        for augment in (teleporters_augment, teleporters_augment, doors_augment, doors_augment, multi_level_augment):
            build.acquire(augment)
        ctx = run_pipeline(grid, len(grid[0]), len(grid), start, goal, build, rng)

        tmap = _full_teleport_map(ctx)
        reachable = sequentially_reachable(
            ctx.grid, start, ctx.extra.get("doors", []), teleport=lambda x, y: tmap.get((x, y)),
        )
        if ctx.goal not in reachable:
            failures.append(seed_val)
    assert not failures, f"unsolvable seeds with all three augments active: {failures}"
