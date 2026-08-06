"""
Tests for the composability bug ctx.frontier fixes (see augments/__init__.py's
AugmentContext/run_pipeline docstrings and docs/progression.md's "Composing
multiple augments' mandatory content" section): before this fix,
TeleportersAugment independently overwrote ctx.goal after placing its own
mandatory chain, so once a second goal-owning augment existed it would have
been the only one whose mandatory content actually sat on the path to the
final goal -- every other active augment's "mandatory" content would become
a real, sealed, reachable, but no-longer-required side room.

Proves not just that the final goal is reachable with both augments intact,
but that disabling *either one's* mandatory content independently, with the
other left fully intact, makes the goal unreachable -- the property that
actually catches a "last one wins" regression.
"""

import random

from maze_game.maze import farthest_reachable_cell, generate_maze
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
    return tmap


def _sequentially_reachable_with_permanent_lock(grid, start, doors, permanent, teleport=None):
    """
    Like doors.py's sequentially_reachable(), but any door cell in
    `permanent` never unlocks regardless of key collection -- simulates
    "the player refuses to (or structurally cannot) ever use this
    mandatory door", the doors-side equivalent of deleting a mandatory
    teleporter pair from the teleport map below.
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


def test_goal_is_always_a_member_of_the_final_mandatory_gated_region():
    """
    Regression guard for the goal-depth bug (see docs/progression.md and
    augments/__init__.py::_finalize_goal): whenever any mandatory content
    was placed, the goal must actually sit inside the innermost gated
    region (ctx.extra["mandatory_gated_cells"]) -- not merely be reachable
    "eventually". A goal placed just outside that region (e.g. in the
    approach corridor to a mandatory pocket) would silently stop requiring
    the full chain.
    """
    failures = []
    for seed_val in SEEDS:
        ctx = _run(seed_val, ("teleporters", 2), ("doors", 2))
        gated = ctx.extra.get("mandatory_gated_cells")
        if not gated:
            continue  # graceful degradation on a cramped maze -- nothing to prove this seed
        if ctx.goal not in gated:
            failures.append(seed_val)
    assert not failures, f"goal placed outside the mandatory-gated region, seeds: {failures}"


def test_goal_depth_has_a_meaningful_floor_with_mandatory_augments_active():
    """
    Regression guard for the goal-depth bug: before the fix, _finalize_goal()
    could place the goal as few as 4 hops from start on a 41x41 maze (a
    near-disconnected candidate graph confining the search to barely more
    than ctx.frontier's own tiny sealed pocket). Confirms a real, meaningfully
    larger floor now holds across a range of seeds.
    """
    from maze_game.maze import shortest_path

    size = 41
    depths = []
    for seed_val in range(20):
        rng = random.Random(4000 + seed_val)
        grid = generate_maze(size, size, rng=rng)
        start = (1, 1)
        build = AugmentBuild()
        _acquire(build, "teleporters", 1)
        _acquire(build, "doors", 1)
        ctx = run_pipeline(grid, size, size, start, farthest_reachable_cell(grid, start), build, rng)
        if not ctx.extra.get("mandatory_gated_cells"):
            continue  # graceful degradation on a cramped maze -- nothing to prove this seed
        tmap = _full_teleport_map(ctx)
        depths.append(len(shortest_path(ctx.grid, start, ctx.goal, extra_edges=tmap)) - 1)

    assert depths, "no seed placed any mandatory content -- test is vacuous"
    assert min(depths) >= 10, f"goal depth fell back near the pre-fix floor: {sorted(depths)}"


def test_goal_placement_is_independent_of_registry_order(monkeypatch):
    """Regression guard against ever reintroducing a "last augment wins"
    ownership bug in a different shape: reversing ALL_AUGMENTS order must
    still produce a fully-gated goal when both augments are active."""
    failures = []
    for seed_val in SEEDS:
        rng = random.Random(2000 + seed_val)
        grid = generate_maze(SIZE, SIZE, rng=rng)
        start = (1, 1)
        goal = farthest_reachable_cell(grid, start)
        build = AugmentBuild()
        _acquire(build, "teleporters", 2)
        _acquire(build, "doors", 2)

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
