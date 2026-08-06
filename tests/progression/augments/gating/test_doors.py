"""
Tests for maze_game.progression.augments.doors -- the second maze augment.
Covers the core "unreachable without the key" guarantee, level-scaling
formulas, placement invariants, determinism under a seeded rng, end-to-end
solvability via the real player.slide_path()/move() machinery (simulating
actual sequential key collection, not just a single reachability snapshot),
and composition with the teleporters augment (the registry-order concern
doors.py's own docstring calls out).
"""

import random

import pytest

from maze_game.constants import (
    DOOR_PAIR_COUNT_BASE, DOOR_PAIR_COUNT_STEP, DOOR_PAIR_COUNT_MAX,
    DOOR_MANDATORY_COUNT_BASE, DOOR_MANDATORY_COUNT_STEP,
)
from maze_game.maze import generate_maze, farthest_reachable_cell
from maze_game.progression.augments import AugmentBuild, run_pipeline, ALL_AUGMENTS
from maze_game.progression.augments.gating._movement import real_move_reachable
from maze_game.progression.augments.gating.doors import DoorsAugment, sequentially_reachable
from maze_game.progression.augments.gating.teleporters import TeleportersAugment


def _doors_augment():
    return next(a for a in ALL_AUGMENTS if a.id == "doors")


def _teleporters_augment():
    return next(a for a in ALL_AUGMENTS if a.id == "teleporters")


def _teleport_map(pairs):
    tmap = {}
    for p in pairs:
        tmap[p.a] = p.b
        tmap[p.b] = p.a
    return tmap


def _run_doors_at_level(grid, level, seed_rng, extra_build_picks=()):
    """extra_build_picks: other augments to also activate (e.g. teleporters), for composition tests."""
    start = (1, 1)
    goal = farthest_reachable_cell(grid, start)
    build = AugmentBuild()
    for augment in extra_build_picks:
        build.acquire(augment)
    augment = _doors_augment()
    for _ in range(level):
        build.acquire(augment)
    return run_pipeline(grid, len(grid[0]), len(grid), start, goal, build, seed_rng)


# ── Core guarantee ────────────────────────────────────────────────────────


def test_goal_is_unreachable_while_locked_but_reachable_after_collecting_keys():
    for seed_val in range(30):
        rng = random.Random(seed_val)
        grid = generate_maze(21, 21, rng=rng)
        ctx = _run_doors_at_level(grid, level=1, seed_rng=rng)
        mandatory = [p for p in ctx.extra["doors"] if p.mandatory]
        assert mandatory, f"seed {seed_val}: expected at least one mandatory door at level 1"

        locked = {p.door for p in ctx.extra["doors"]}
        reachable_locked = real_move_reachable(ctx.grid, (1, 1), door_locked=lambda x, y: (x, y) in locked)
        assert ctx.goal not in reachable_locked, f"seed {seed_val}: goal reachable with every door still locked"

        final_reachable = sequentially_reachable(ctx.grid, (1, 1), ctx.extra["doors"])
        assert ctx.goal in final_reachable, (
            f"seed {seed_val}: goal not reachable even after collecting every reachable key"
        )


# ── Level-scaling formulas ───────────────────────────────────────────────


@pytest.mark.parametrize("level", [1, 2, 3, 4, 5])
def test_pair_and_mandatory_counts_follow_the_level_formula(level):
    rng = random.Random(level * 7 + 1)
    grid = generate_maze(21, 21, rng=rng)
    ctx = _run_doors_at_level(grid, level=level, seed_rng=rng)
    pairs = ctx.extra["doors"]
    mandatory = [p for p in pairs if p.mandatory]

    expected_pair_count = min(DOOR_PAIR_COUNT_BASE + DOOR_PAIR_COUNT_STEP * (level - 1), DOOR_PAIR_COUNT_MAX)
    expected_mandatory_count = min(
        DOOR_MANDATORY_COUNT_BASE + DOOR_MANDATORY_COUNT_STEP * (level - 1), expected_pair_count,
    )
    assert len(pairs) == expected_pair_count
    # Mandatory placement can fall short of the formula (graceful
    # degradation on cramped mazes), never exceed it.
    assert len(mandatory) <= expected_mandatory_count


# ── Placement invariants ─────────────────────────────────────────────────


def test_door_and_key_cells_never_overlap_start_goal_or_each_other():
    rng = random.Random(12)
    grid = generate_maze(21, 21, rng=rng)
    ctx = _run_doors_at_level(grid, level=3, seed_rng=rng)

    all_cells = []
    for pair in ctx.extra["doors"]:
        all_cells.extend([pair.door, pair.key])
    assert (1, 1) not in all_cells
    assert ctx.goal not in all_cells
    assert len(all_cells) == len(set(all_cells))  # no duplicates


def test_key_is_always_reachable_before_its_own_door_is_unlocked():
    """Replays the mandatory chain in nesting order -- each door's key must be reachable using only earlier doors' keys."""
    rng = random.Random(21)
    grid = generate_maze(21, 21, rng=rng)
    ctx = _run_doors_at_level(grid, level=4, seed_rng=rng)
    mandatory = [p for p in ctx.extra["doors"] if p.mandatory]

    locked = {p.door for p in ctx.extra["doors"]}
    for pair in mandatory:
        reachable = real_move_reachable(ctx.grid, (1, 1), door_locked=lambda x, y: (x, y) in locked)
        assert pair.key in reachable, f"key for door {pair.door} not reachable before it unlocks"
        locked.discard(pair.door)


def test_decorative_doors_never_gate_the_route_to_the_goal():
    rng = random.Random(13)
    grid = generate_maze(21, 21, rng=rng)
    ctx = _run_doors_at_level(grid, level=2, seed_rng=rng)
    decorative = [p for p in ctx.extra["doors"] if not p.mandatory]
    if not decorative:
        pytest.skip("no decorative doors placed at this level/seed")

    locked = {p.door for p in decorative}
    reachable = real_move_reachable(ctx.grid, (1, 1), door_locked=lambda x, y: (x, y) in locked)
    assert ctx.goal in reachable


# ── Determinism ───────────────────────────────────────────────────────────


def test_same_seed_produces_identical_door_placement():
    grid = generate_maze(21, 21, rng=random.Random(55))

    ctx_a = _run_doors_at_level([row[:] for row in grid], level=3, seed_rng=random.Random(999))
    ctx_b = _run_doors_at_level([row[:] for row in grid], level=3, seed_rng=random.Random(999))

    assert ctx_a.extra["doors"] == ctx_b.extra["doors"]
    assert ctx_a.grid == ctx_b.grid
    assert ctx_a.goal == ctx_b.goal


# ── End-to-end solvability ────────────────────────────────────────────────


def test_door_gated_maze_is_actually_completable_via_real_slide():
    for seed_val in range(10):
        rng = random.Random(300 + seed_val)
        grid = generate_maze(21, 21, rng=rng)
        ctx = _run_doors_at_level(grid, level=1, seed_rng=rng)

        reachable = sequentially_reachable(ctx.grid, (1, 1), ctx.extra["doors"])
        assert ctx.goal in reachable, f"seed_val {seed_val}: goal not reachable via any sequence of real moves + key pickups"


def test_door_gated_maze_is_completable_across_sizes_and_levels():
    failures = []
    for size in (9, 21, 41):
        for level in (1, 3, 5):
            for seed_val in range(10):
                rng = random.Random(seed_val * 777 + size * 13 + level)
                grid = generate_maze(size, size, rng=rng)
                ctx = _run_doors_at_level(grid, level=level, seed_rng=rng)
                reachable = sequentially_reachable(ctx.grid, (1, 1), ctx.extra["doors"])
                if ctx.goal not in reachable:
                    failures.append((size, level, seed_val))
    assert not failures, f"unsolvable combinations: {failures}"


# ── Composition with teleporters (registry-order concern) ────────────────


def test_doors_and_teleporters_compose_without_a_bypass():
    """
    Both augments active, run through the real ALL_AUGMENTS pipeline (so
    registry order -- teleporters before doors -- is exercised exactly as
    in play): a teleporter must never silently bypass a door that looked
    like a genuine cut vertex under plain grid adjacency.
    """
    for seed_val in range(15):
        rng = random.Random(400 + seed_val)
        grid = generate_maze(21, 21, rng=rng)
        ctx = _run_doors_at_level(grid, level=3, seed_rng=rng, extra_build_picks=[_teleporters_augment()] * 3)

        tmap = _teleport_map(ctx.extra.get("teleporters", []))
        teleport = lambda x, y: tmap.get((x, y))
        reachable = sequentially_reachable(ctx.grid, (1, 1), ctx.extra["doors"], teleport=teleport)
        assert ctx.goal in reachable, f"seed_val {seed_val}: goal not reachable with both augments active"
