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
from itertools import combinations

from maze_game.maze import generate_maze, farthest_reachable_cell, bfs_reachable
from maze_game.progression.augments import AugmentBuild, run_pipeline, ALL_AUGMENTS
from maze_game.progression.augments._movement import real_move_reachable
from maze_game.progression.augments.doors import sequentially_reachable


def _multi_level_augment():
    return next(a for a in ALL_AUGMENTS if a.id == "multi_level")


def _stairs_map(floors):
    tmap = {}
    for link in floors:
        tmap[link.down] = link.up
        tmap[link.up] = link.down
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
    any single mandatory floor's `down` cell (as if the player refused to
    use it) must make the goal unreachable, proving every mandatory floor
    -- not just the deepest one -- sits on the only path to the goal."""
    rng = random.Random(4242)
    grid = generate_maze(25, 25, rng=rng)
    ctx = _run_multi_level_at_level(grid, level=3, seed_rng=rng)
    mandatory = [f for f in ctx.extra["floors"] if f.mandatory]
    assert len(mandatory) >= 2, "expected level 3 to place >=2 mandatory floors on this seed"

    full_tmap = _full_teleport_map(ctx)
    for skip in mandatory:
        tmap = dict(full_tmap)
        del tmap[skip.down]
        del tmap[skip.up]
        reachable = sequentially_reachable(
            ctx.grid, (1, 1), ctx.extra.get("doors", []), teleport=lambda x, y: tmap.get((x, y)),
        )
        assert ctx.goal not in reachable, (
            f"goal still reachable while floor {skip.floor}'s stairs ({skip.down}<->{skip.up}) are disabled"
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
        all_cells.extend([link.down, link.up])
    assert (1, 1) not in all_cells
    assert ctx.goal not in all_cells
    assert len(all_cells) == len(set(all_cells))  # no duplicates


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
    Checked both ways, same rigor docs/progression.md calls out: plain
    bfs_reachable() must NOT reach the goal (proving the mandatory gates
    are a real partition, not just decoration), while the full
    sequentially_reachable() simulation (real moves, every teleporter/
    stairs hop, every key collectible in some valid order) must.
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

        mandatory_teleporters = [p for p in ctx.extra.get("teleporters", []) if p.mandatory]
        mandatory_floors = [f for f in ctx.extra.get("floors", []) if f.mandatory]
        assert mandatory_teleporters or mandatory_floors, (
            f"seed_val {seed_val}: expected at least one mandatory teleporter pair or floor"
        )
        if ctx.goal in bfs_reachable(ctx.grid, start):
            failures.append((seed_val, "goal reachable without ever using a mandatory gate"))

        tmap = _full_teleport_map(ctx)
        reachable = sequentially_reachable(
            ctx.grid, start, ctx.extra.get("doors", []), teleport=lambda x, y: tmap.get((x, y)),
        )
        if ctx.goal not in reachable:
            failures.append((seed_val, "goal unreachable even via the full sequential-unlock simulation"))
    assert not failures, f"failures with all three augments active: {failures}"


def test_every_combination_of_active_gating_augments_forces_every_gate():
    """
    Extends the "forced-use" standard each augment's own test suite already
    holds itself to individually (bfs_reachable() must fail while
    sequentially_reachable() must succeed) to every *combination* of
    currently-composable augments, not just each one alone. Playtesting
    found a maze where a Teleporters placement let the goal be reached
    without ever needing a Doors key -- a bug in how two gating augments
    *interacted*, invisible to either augment's own solo test suite. This
    checks all `2**3 - 1` non-empty subsets of {teleporters, doors,
    multi_level} (every combination up to MAX_ACTIVE_AUGMENTS, since only
    3 gating augments exist yet -- extend this loop the day a 4th one
    ships) at a level high enough to guarantee at least one mandatory gate
    each, and requires that the goal is:
      1. reachable at all (sequentially_reachable(), the real "can the
         player actually finish this maze" ground truth -- real movement,
         teleport links, and progressive door unlocking as keys are
         found), and
      2. NOT reachable via `real_move_reachable()` with every door
         permanently locked and no teleport/stairs link available at all --
         i.e. there is no route to the goal that avoids using *every*
         active gating mechanism at least once. This is the actual
         "Doors/Teleporters/Multi-Level could be skipped entirely" check:
         (1) alone would pass even if one active augment turned out to be
         fully bypassable, exactly like the original bug report.
    """
    teleporters_augment = next(a for a in ALL_AUGMENTS if a.id == "teleporters")
    doors_augment = next(a for a in ALL_AUGMENTS if a.id == "doors")
    multi_level_augment = _multi_level_augment()
    by_id = {
        "teleporters": teleporters_augment,
        "doors": doors_augment,
        "multi_level": multi_level_augment,
    }

    failures = []
    seed_val = 0
    for size in range(1, len(by_id) + 1):
        for combo in combinations(sorted(by_id), size):
            for _ in range(5):
                seed_val += 1
                rng = random.Random(1000 + seed_val)
                grid = generate_maze(25, 25, rng=rng)
                start = (1, 1)
                goal = farthest_reachable_cell(grid, start)
                build = AugmentBuild()
                for aid in combo:
                    # Level 3: high enough that every gating augment in the
                    # combo places at least one real mandatory gate (see
                    # each module's own MANDATORY_COUNT_* constants).
                    for _ in range(3):
                        build.acquire(by_id[aid])
                ctx = run_pipeline(grid, len(grid[0]), len(grid), start, goal, build, rng)

                tmap = _full_teleport_map(ctx)
                doors = ctx.extra.get("doors", [])
                real_reachable = sequentially_reachable(
                    ctx.grid, start, doors, teleport=lambda x, y: tmap.get((x, y)),
                )
                if ctx.goal not in real_reachable:
                    failures.append((combo, seed_val, "goal unreachable even after real play"))
                    continue

                door_cells = {pair.door for pair in doors}
                no_gate_reachable = real_move_reachable(
                    ctx.grid, start, door_locked=lambda x, y: (x, y) in door_cells,
                )
                if ctx.goal in no_gate_reachable:
                    failures.append((combo, seed_val, "goal reachable without using any active gate"))

    assert not failures, f"combination(s) let a gate be skipped or broke solvability: {failures}"
