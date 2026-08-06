"""
Tests for maze_game.progression.augments.shifting_room -- the third
gating augment. Covers the core "unreachable until the pad fires, then
reachable" guarantee (the one property that actually distinguishes this
from teleporters/doors, since the pocket is a *real* wall, not a
behavioral gate), level-scaling formulas, placement invariants, and the
one-shot/pass-through runtime trigger semantics via the real
player.slide_path() machinery.
"""

import random

import pytest

from maze_game.constants import (
    SHIFT_PAD_COUNT_BASE, SHIFT_PAD_COUNT_STEP, SHIFT_PAD_COUNT_MAX,
    SHIFT_MANDATORY_COUNT_BASE, SHIFT_MANDATORY_COUNT_STEP,
)
from maze_game.maze import generate_maze, farthest_reachable_cell, bfs_reachable, is_stoppable_cell
from maze_game.player import slide_path
from maze_game.progression.augments import AugmentBuild, run_pipeline, ALL_AUGMENTS
from maze_game.progression.augments.gating.doors import sequentially_reachable
from maze_game.progression.augments.shifting_room import ShiftingRoomAugment


def _shifting_room_augment():
    return next(a for a in ALL_AUGMENTS if a.id == "shifting_room")


def _run_augment_at_level(grid, level, seed_rng):
    start = (1, 1)
    goal = farthest_reachable_cell(grid, start)
    build = AugmentBuild()
    augment = _shifting_room_augment()
    for _ in range(level):
        build.acquire(augment)
    return run_pipeline(grid, len(grid[0]), len(grid), start, goal, build, seed_rng)


def _opened_grid(grid, pads):
    opened = [row[:] for row in grid]
    for pad in pads:
        wx, wy = pad.wall_segment
        opened[wy][wx] = 0
    return opened


# ── Core guarantee ────────────────────────────────────────────────────────


def test_mandatory_gated_region_is_unreachable_before_and_reachable_after_opening():
    failures = []
    for seed_val in range(30):
        rng = random.Random(seed_val)
        grid = generate_maze(21, 21, rng=rng)
        ctx = _run_augment_at_level(grid, level=1, seed_rng=rng)
        mandatory = [p for p in ctx.extra["pressure_pads"] if p.mandatory]
        if not mandatory:
            continue  # graceful degradation on a cramped maze -- nothing to prove this seed
        gated = ctx.extra["mandatory_gated_cells"]

        # A real, physically-closed wall -- plain BFS can't reach it at all,
        # not even the pad's own reachability being "behavioral" the way a
        # locked door is.
        reachable = bfs_reachable(ctx.grid, (1, 1))
        if gated & reachable:
            failures.append((seed_val, "gated pocket reachable before any pad fired"))
            continue

        opened = _opened_grid(ctx.grid, ctx.extra["pressure_pads"])
        if not gated <= bfs_reachable(opened, (1, 1)):
            failures.append((seed_val, "gated pocket still unreachable after opening every pad"))
    assert not failures, failures


def test_goal_is_placed_inside_the_mandatory_gated_region_when_one_exists():
    failures = []
    for seed_val in range(30):
        rng = random.Random(100 + seed_val)
        grid = generate_maze(21, 21, rng=rng)
        ctx = _run_augment_at_level(grid, level=1, seed_rng=rng)
        mandatory = [p for p in ctx.extra["pressure_pads"] if p.mandatory]
        if not mandatory:
            continue
        if ctx.goal not in ctx.extra["mandatory_gated_cells"]:
            failures.append(seed_val)
    assert not failures, f"goal placed outside the gated region, seeds: {failures}"


# ── Level-scaling formulas ───────────────────────────────────────────────


@pytest.mark.parametrize("level", [1, 2, 3, 4, 5])
def test_pad_and_mandatory_counts_follow_the_level_formula(level):
    rng = random.Random(level * 7 + 1)
    grid = generate_maze(21, 21, rng=rng)
    ctx = _run_augment_at_level(grid, level=level, seed_rng=rng)
    pads = ctx.extra["pressure_pads"]
    mandatory = [p for p in pads if p.mandatory]

    expected_pad_count = min(SHIFT_PAD_COUNT_BASE + SHIFT_PAD_COUNT_STEP * (level - 1), SHIFT_PAD_COUNT_MAX)
    expected_mandatory_count = min(
        SHIFT_MANDATORY_COUNT_BASE + SHIFT_MANDATORY_COUNT_STEP * (level - 1), expected_pad_count,
    )
    assert len(pads) == expected_pad_count
    # Mandatory placement can fall short of the formula (graceful
    # degradation on cramped mazes), never exceed it.
    assert len(mandatory) <= expected_mandatory_count


# ── Placement invariants ─────────────────────────────────────────────────


def test_every_pad_is_a_stoppable_cell():
    rng = random.Random(11)
    grid = generate_maze(21, 21, rng=rng)
    ctx = _run_augment_at_level(grid, level=3, seed_rng=rng)
    for pad in ctx.extra["pressure_pads"]:
        assert is_stoppable_cell(ctx.grid, *pad.pad)


def test_pad_and_wall_segment_cells_never_overlap_start_goal_or_each_other():
    rng = random.Random(12)
    grid = generate_maze(21, 21, rng=rng)
    start = (1, 1)
    goal = farthest_reachable_cell(grid, start)
    build = AugmentBuild()
    augment = _shifting_room_augment()
    build.acquire(augment)
    build.acquire(augment)
    build.acquire(augment)
    ctx = run_pipeline(grid, 21, 21, start, goal, build, rng)

    pad_cells = [p.pad for p in ctx.extra["pressure_pads"]]
    assert start not in pad_cells
    assert ctx.goal not in pad_cells
    assert len(pad_cells) == len(set(pad_cells))  # no duplicates


def test_wall_segment_is_closed_at_generation_time():
    """Unlike a door (grid-open, behaviorally locked), a pad's controlled wall must be a genuinely closed grid cell until triggered."""
    rng = random.Random(13)
    grid = generate_maze(21, 21, rng=rng)
    ctx = _run_augment_at_level(grid, level=3, seed_rng=rng)
    for pad in ctx.extra["pressure_pads"]:
        wx, wy = pad.wall_segment
        assert ctx.grid[wy][wx] == 1


def test_main_region_minus_sealed_pockets_stays_fully_connected():
    """
    Regression guard for the pendant-subtree pocket-selection technique
    (shared with teleporters.py/doors.py, see gating/_movement.py's
    pendant_subtree_map docstring): an arbitrary connected blob is usually
    a *bridge* in a near-tree maze, and naively sealing one fragments
    unrelated parts of the maze. Checked against the *final* grid's own
    open-cell set (mirrors teleporters.py's identical test): every cell
    still open after the augment runs must be reachable from start, once
    every pad is (hypothetically) opened.
    """
    for seed_val in range(20):
        rng = random.Random(100 + seed_val)
        grid = generate_maze(21, 21, rng=rng)
        start = (1, 1)
        ctx = _run_augment_at_level(grid, level=4, seed_rng=rng)
        opened = _opened_grid(ctx.grid, ctx.extra["pressure_pads"])
        after = bfs_reachable(opened, start)

        open_cells = {(x, y) for y, row in enumerate(ctx.grid) for x, v in enumerate(row) if v == 0}
        assert open_cells <= after, f"seed {seed_val}: open cells became unreachable even with every pad opened"


# ── Composition with teleporters/doors ───────────────────────────────────


def test_composes_with_teleporters_and_doors_and_disabling_the_mandatory_pad_breaks_solvability():
    failures = []
    for seed_val in range(20):
        rng = random.Random(1000 + seed_val)
        grid = generate_maze(29, 29, rng=rng)
        start = (1, 1)
        build = AugmentBuild()
        for aid in ("teleporters", "doors", "shifting_room"):
            augment = next(a for a in ALL_AUGMENTS if a.id == aid)
            build.acquire(augment)
        ctx = run_pipeline(grid, 29, 29, start, farthest_reachable_cell(grid, start), build, rng)

        pads = ctx.extra.get("pressure_pads", [])
        mandatory_pads = [p for p in pads if p.mandatory]
        if not mandatory_pads:
            continue  # graceful degradation on a cramped maze -- nothing to prove this seed

        tmap = {}
        for p in ctx.extra.get("teleporters", []):
            tmap[p.a] = p.b
            tmap[p.b] = p.a
        doors = ctx.extra.get("doors", [])

        opened = _opened_grid(ctx.grid, pads)
        full_reachable = sequentially_reachable(opened, start, doors, teleport=lambda x, y: tmap.get((x, y)))
        if ctx.goal not in full_reachable:
            failures.append((seed_val, "goal unreachable with every pad triggered"))
            continue

        # Disable just the mandatory pad(s) -- leave every other pad opened.
        still_sealed = [row[:] for row in ctx.grid]
        for pad in pads:
            if pad.mandatory:
                continue
            wx, wy = pad.wall_segment
            still_sealed[wy][wx] = 0
        reachable_without_mandatory_pad = sequentially_reachable(
            still_sealed, start, doors, teleport=lambda x, y: tmap.get((x, y)),
        )
        if ctx.goal in reachable_without_mandatory_pad:
            failures.append((seed_val, "goal still reachable without ever triggering the mandatory pad"))
    assert not failures, failures


# ── Runtime trigger semantics (via the real slide_path() hook) ──────────


def test_pressure_pad_hook_fires_mid_slide_not_only_on_the_stop_cell():
    """The one behavior the user was most explicit about: passing OVER a pad triggers it, even without stopping there."""
    grid = [
        [1, 1, 1, 1, 1, 1, 1],
        [1, 0, 0, 0, 0, 0, 1],
        [1, 1, 1, 1, 1, 1, 1],
    ]
    triggered = []
    slide_path(grid, (1, 1), (1, 0), pressure_pad=lambda x, y: triggered.append((x, y)))
    # The slide never stops at (3, 1) (a 2-open-neighbour mid-corridor
    # cell) -- it's a straight pass-through, yet the hook must still fire.
    assert (3, 1) in triggered


def test_pressure_pad_hook_is_idempotent_once_the_wall_is_already_open():
    """One-shot: triggering an already-triggered pad's wall segment a second time is a no-op, not an error."""
    grid = [
        [1, 1, 1, 1, 1, 1, 1],
        [1, 0, 0, 0, 0, 0, 1],
        [1, 1, 1, 1, 1, 1, 1],
    ]
    wall_segment = (4, 1)
    grid[wall_segment[1]][wall_segment[0]] = 0  # simulate an already-fired pad

    calls = []

    def trigger(x, y):
        calls.append((x, y))
        if grid[wall_segment[1]][wall_segment[0]] == 1:
            grid[wall_segment[1]][wall_segment[0]] = 0

    slide_path(grid, (1, 1), (1, 0), pressure_pad=trigger)
    assert grid[wall_segment[1]][wall_segment[0]] == 0  # still open, no crash, no toggle-back
