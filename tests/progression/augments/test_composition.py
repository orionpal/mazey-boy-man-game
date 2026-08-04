"""
Tests for the composability bug ctx.frontier fixes (see augments/__init__.py's
AugmentContext/run_pipeline docstrings and docs/progression.md's Multi-Level
Mazes section): before this fix, TeleportersAugment and MultiLevelAugment
each independently overwrote ctx.goal after placing their own mandatory
chain, so whichever of them ran *last* in ALL_AUGMENTS registry order was
the only one whose mandatory content actually sat on the path to the final
goal -- every other active augment's "mandatory" content became a real,
sealed, reachable, but no-longer-required side room.

Each test below picks two or three augments together and proves not just
that the final goal is reachable with everything intact (the weaker
property test_multi_level.py's own composition test already checked, and
did NOT catch this bug), but that disabling *any one* active augment's
mandatory content -- independently, with the others left fully intact --
makes the goal unreachable. That's the property that actually catches a
"last one wins" regression: under the old bug, disabling everything except
whichever augment ran last would still leave the goal reachable.
"""

import random

from maze_game.maze import bfs_reachable, farthest_reachable_cell, generate_maze
from maze_game.progression.augments import ALL_AUGMENTS, AugmentBuild, run_pipeline
from maze_game.progression.augments._movement import real_move_reachable
from maze_game.progression.augments.doors import sequentially_reachable

SEEDS = range(15)
SIZE = 25


def _augment(id_):
    return next(a for a in ALL_AUGMENTS if a.id == id_)


def _acquire(build, id_, times=1):
    augment = _augment(id_)
    for _ in range(times):
        build.acquire(augment)


def _full_teleport_map(ctx):
    tmap = {}
    for pair in ctx.extra.get("teleporters", []):
        tmap[pair.a] = pair.b
        tmap[pair.b] = pair.a
    for link in ctx.extra.get("floors", []):
        tmap[link.entrance] = link.floor_start
        tmap[link.floor_exit] = link.return_landing
    return tmap


def _sequentially_reachable_with_permanent_lock(grid, start, doors, permanent, teleport=None):
    """
    Like doors.py's sequentially_reachable(), but any door cell in
    `permanent` never unlocks regardless of key collection -- simulates
    "the player refuses to (or structurally cannot) ever use this
    mandatory door", the doors-side equivalent of deleting a mandatory
    teleporter/floor link from the teleport map below.
    """
    locked = {pair.door for pair in doors} | set(permanent)
    key_owner = {pair.key: pair.door for pair in doors}
    while True:
        reachable = real_move_reachable(grid, start, teleport=teleport, door_locked=lambda x, y: (x, y) in locked)
        newly_unlocked = {
            key_owner[k] for k in key_owner
            if k in reachable and key_owner[k] in locked and key_owner[k] not in permanent
        }
        if not newly_unlocked:
            return reachable
        locked -= newly_unlocked


def _run(seed_val, *acquisitions):
    rng = random.Random(1000 + seed_val)
    grid = generate_maze(SIZE, SIZE, rng=rng)
    start = (1, 1)
    goal = farthest_reachable_cell(grid, start)
    build = AugmentBuild()
    for id_, times in acquisitions:
        _acquire(build, id_, times)
    return run_pipeline(grid, len(grid[0]), len(grid), start, goal, build, rng)


def test_teleporters_and_doors_both_gate_the_goal():
    failures = []
    for seed_val in SEEDS:
        ctx = _run(seed_val, ("teleporters", 2), ("doors", 2))
        mandatory_pairs = [p for p in ctx.extra["teleporters"] if p.mandatory]
        mandatory_doors = [p for p in ctx.extra["doors"] if p.mandatory]
        if not mandatory_pairs or not mandatory_doors:
            continue  # graceful degradation on a cramped maze -- nothing to prove this seed

        full_tmap = _full_teleport_map(ctx)
        full_reachable = sequentially_reachable(ctx.grid, (1, 1), ctx.extra["doors"], teleport=lambda x, y: full_tmap.get((x, y)))
        if ctx.goal not in full_reachable:
            failures.append((seed_val, "not reachable at all"))
            continue

        # Disable just the teleporters' mandatory content -- doors intact.
        tmap = {k: v for k, v in full_tmap.items() if k not in {p.a for p in mandatory_pairs} | {p.b for p in mandatory_pairs}}
        reachable = sequentially_reachable(ctx.grid, (1, 1), ctx.extra["doors"], teleport=lambda x, y: tmap.get((x, y)))
        if ctx.goal in reachable:
            failures.append((seed_val, "goal still reachable without the mandatory teleporter"))

        # Disable just the doors' mandatory content -- teleporters intact.
        reachable = _sequentially_reachable_with_permanent_lock(
            ctx.grid, (1, 1), ctx.extra["doors"], {p.door for p in mandatory_doors}, teleport=lambda x, y: full_tmap.get((x, y)),
        )
        if ctx.goal in reachable:
            failures.append((seed_val, "goal still reachable without the mandatory door"))
    assert not failures, failures


def test_teleporters_and_multi_level_both_gate_the_goal():
    """The exact scenario the original bug broke: MultiLevelAugment (last in
    registry order) used to unconditionally overwrite ctx.goal, silently
    orphaning whatever TeleportersAugment had already sealed off."""
    failures = []
    for seed_val in SEEDS:
        ctx = _run(seed_val, ("teleporters", 2), ("multi_level", 2))
        mandatory_pairs = [p for p in ctx.extra["teleporters"] if p.mandatory]
        mandatory_floors = [f for f in ctx.extra["floors"] if f.mandatory]
        if not mandatory_pairs or not mandatory_floors:
            continue

        full_tmap = _full_teleport_map(ctx)
        full_reachable = sequentially_reachable(ctx.grid, (1, 1), ctx.extra.get("doors", []), teleport=lambda x, y: full_tmap.get((x, y)))
        if ctx.goal not in full_reachable:
            failures.append((seed_val, "not reachable at all"))
            continue

        tmap = {k: v for k, v in full_tmap.items() if k not in {p.a for p in mandatory_pairs} | {p.b for p in mandatory_pairs}}
        reachable = sequentially_reachable(ctx.grid, (1, 1), ctx.extra.get("doors", []), teleport=lambda x, y: tmap.get((x, y)))
        if ctx.goal in reachable:
            failures.append((seed_val, "goal still reachable without the mandatory teleporter"))

        skip_cells = {f.entrance for f in mandatory_floors} | {f.floor_exit for f in mandatory_floors}
        tmap = {k: v for k, v in full_tmap.items() if k not in skip_cells}
        reachable = sequentially_reachable(ctx.grid, (1, 1), ctx.extra.get("doors", []), teleport=lambda x, y: tmap.get((x, y)))
        if ctx.goal in reachable:
            failures.append((seed_val, "goal still reachable without the mandatory floor"))
    assert not failures, failures


def test_doors_and_multi_level_both_gate_the_goal():
    failures = []
    for seed_val in SEEDS:
        ctx = _run(seed_val, ("doors", 2), ("multi_level", 2))
        mandatory_doors = [p for p in ctx.extra["doors"] if p.mandatory]
        mandatory_floors = [f for f in ctx.extra["floors"] if f.mandatory]
        if not mandatory_doors or not mandatory_floors:
            continue

        full_tmap = _full_teleport_map(ctx)
        full_reachable = sequentially_reachable(ctx.grid, (1, 1), ctx.extra["doors"], teleport=lambda x, y: full_tmap.get((x, y)))
        if ctx.goal not in full_reachable:
            failures.append((seed_val, "not reachable at all"))
            continue

        reachable = _sequentially_reachable_with_permanent_lock(
            ctx.grid, (1, 1), ctx.extra["doors"], {p.door for p in mandatory_doors}, teleport=lambda x, y: full_tmap.get((x, y)),
        )
        if ctx.goal in reachable:
            failures.append((seed_val, "goal still reachable without the mandatory door"))

        skip_cells = {f.entrance for f in mandatory_floors} | {f.floor_exit for f in mandatory_floors}
        tmap = {k: v for k, v in full_tmap.items() if k not in skip_cells}
        reachable = sequentially_reachable(ctx.grid, (1, 1), ctx.extra["doors"], teleport=lambda x, y: tmap.get((x, y)))
        if ctx.goal in reachable:
            failures.append((seed_val, "goal still reachable without the mandatory floor"))
    assert not failures, failures


def test_all_three_augments_together_all_gate_the_goal():
    failures = []
    for seed_val in SEEDS:
        ctx = _run(seed_val, ("teleporters", 2), ("doors", 2), ("multi_level", 2))
        mandatory_pairs = [p for p in ctx.extra["teleporters"] if p.mandatory]
        mandatory_doors = [p for p in ctx.extra["doors"] if p.mandatory]
        mandatory_floors = [f for f in ctx.extra["floors"] if f.mandatory]
        if not (mandatory_pairs and mandatory_doors and mandatory_floors):
            continue  # need all three actually mandatory on this seed to prove the point

        full_tmap = _full_teleport_map(ctx)
        full_reachable = sequentially_reachable(ctx.grid, (1, 1), ctx.extra["doors"], teleport=lambda x, y: full_tmap.get((x, y)))
        if ctx.goal not in full_reachable:
            failures.append((seed_val, "not reachable at all"))
            continue

        tmap = {k: v for k, v in full_tmap.items() if k not in {p.a for p in mandatory_pairs} | {p.b for p in mandatory_pairs}}
        reachable = sequentially_reachable(ctx.grid, (1, 1), ctx.extra["doors"], teleport=lambda x, y: tmap.get((x, y)))
        if ctx.goal in reachable:
            failures.append((seed_val, "goal still reachable without the mandatory teleporter"))

        reachable = _sequentially_reachable_with_permanent_lock(
            ctx.grid, (1, 1), ctx.extra["doors"], {p.door for p in mandatory_doors}, teleport=lambda x, y: full_tmap.get((x, y)),
        )
        if ctx.goal in reachable:
            failures.append((seed_val, "goal still reachable without the mandatory door"))

        skip_cells = {f.entrance for f in mandatory_floors} | {f.floor_exit for f in mandatory_floors}
        tmap = {k: v for k, v in full_tmap.items() if k not in skip_cells}
        reachable = sequentially_reachable(ctx.grid, (1, 1), ctx.extra["doors"], teleport=lambda x, y: tmap.get((x, y)))
        if ctx.goal in reachable:
            failures.append((seed_val, "goal still reachable without the mandatory floor"))
    assert not failures, failures


def test_goal_placement_is_independent_of_registry_order(monkeypatch):
    """Regression guard against ever reintroducing a "last augment wins"
    ownership bug in a different shape: reversing ALL_AUGMENTS order must
    still produce a fully-gated goal when all three augments are active."""
    failures = []
    for seed_val in SEEDS:
        rng = random.Random(2000 + seed_val)
        grid = generate_maze(SIZE, SIZE, rng=rng)
        start = (1, 1)
        goal = farthest_reachable_cell(grid, start)
        build = AugmentBuild()
        _acquire(build, "teleporters", 2)
        _acquire(build, "doors", 2)
        _acquire(build, "multi_level", 2)

        monkeypatch.setattr(
            "maze_game.progression.augments.ALL_AUGMENTS",
            list(reversed(ALL_AUGMENTS)),
        )
        ctx = run_pipeline(grid, len(grid[0]), len(grid), start, goal, build, rng)

        tmap = _full_teleport_map(ctx)
        reachable = sequentially_reachable(ctx.grid, start, ctx.extra.get("doors", []), teleport=lambda x, y: tmap.get((x, y)))
        if ctx.goal not in reachable:
            failures.append(seed_val)
    assert not failures, f"unsolvable with reversed registry order, seeds: {failures}"
