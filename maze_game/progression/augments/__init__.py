"""
augments/__init__.py
---------------------
Maze augments: generation-time modifiers (teleporting squares, doors &
keys, and later rotating maze, fog of war, shifting rooms -- see
docs/planning/future-ideas.md) offered every AUGMENT_INTERVAL-th maze
alongside the perk/item shop. Mirrors shop/'s shape (a Build-like
pick-count tracker, a card-offer function) but for maze generation instead
of runtime abilities.

An augment's *level* is just its pick count (AugmentBuild.picks[id]),
identical to how perk stacking already works (shop/perks.py::Build) --
picking the same augment again levels it up rather than doing nothing.

Every active augment (level > 0) gets a chance to mutate the generated grid
via Augment.apply(), in a fixed pipeline (run_pipeline()) called from
progression/run.py::_begin_maze() *after* generate_maze() returns -- the
augment pipeline is a deliberate post-process step, not a change to
generate_maze()'s own interface (see docs/maze-generation.md's "Proposed
near-term plan": generate_maze(cols, rows) -> grid stays the stable
interface). Up to MAX_ACTIVE_AUGMENTS augments can be active in the same
run, all composing through the same pipeline.

Deliberately no generic contact()/render() hook here -- mirrors the
project's existing precedent (hazards.py/renderer.py: bespoke draw
methods, not a generic dispatch). Augment.apply() is the only shared
generation-time hook; an augment's run-time behaviour (e.g. teleporters.py's
contact effect, or a runtime/ augment's entirely-apply()-free effect --
see that package's docstring) wires directly into
player.slide_path()/progression/run.py/progression/renderer.py instead.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Any

from maze_game.constants import (
    MAX_ACTIVE_AUGMENTS,
    TWIN_GOAL_MIN_START_DISTANCE_FRACTION, TWIN_GOAL_MIN_GOAL_DISTANCE_FRACTION,
)
from maze_game.maze import farthest_reachable_cell, secondary_goal_candidate

AUGMENT_CARDS_OFFERED = 3  # mirrors shop/__init__.py::SHOP_CARDS_OFFERED


class Augment:
    """Base for a maze-generation-time modifier. Concrete augments live in gating/ or runtime/ (see those packages' docstrings)."""

    id: str
    name: str
    description: str

    def apply(self, ctx: "AugmentContext") -> None:
        raise NotImplementedError


@dataclass
class AugmentContext:
    """
    Mutable bundle threaded through the augment pipeline. `grid` may be
    reassigned by an augment's apply() (e.g. teleporters seals off part of
    the grid) -- later augments in the pipeline must treat it as
    already-possibly-mutated, not the raw generate_maze() output.
    `reserved` accumulates cells any augment has claimed (teleporter pads,
    sealed-pocket boundaries, ...) so later augments and entity spawning
    (pellets/hazards) can avoid them.

    `goal` is NOT meant to be reassigned by an individual augment anymore
    (see `frontier` below and `_finalize_goal()`) -- it starts as the plain
    generate_maze() default and is only ever overwritten once, centrally,
    after every augment has run.

    `frontier` is the shared "current end of the mandatory chain" every
    augment's mandatory-content placement must both read (as its own
    search root, instead of `start`) and advance (to wherever its own
    mandatory chain ends) before returning. This is what makes multiple
    active augments' mandatory content compose into ONE nested critical
    path instead of each independently claiming the goal and silently
    orphaning whichever augment didn't run last (a real bug this field
    fixes -- see docs/progression.md's "Composing multiple augments'
    mandatory content" section and
    tests/progression/augments/gating/test_composition.py). Starts at `start`;
    staying there means no augment has placed mandatory content yet.
    """

    grid: list[list[int]]
    cols: int
    rows: int
    start: tuple[int, int]
    goal: tuple[int, int]
    rng: random.Random
    level: int = 0
    reserved: set[tuple[int, int]] = field(default_factory=set)
    extra: dict[str, Any] = field(default_factory=dict)
    frontier: tuple[int, int] | None = None


class AugmentBuild:
    """
    The player's accumulated augment picks for this run -- reset on death,
    same lifecycle as shop/perks.py::Build. `picks[id]` IS the augment's
    level (1 on first pick, 2 on a repeat pick, ...).
    """

    def __init__(self) -> None:
        self.picks: dict[str, int] = {}

    def acquire(self, augment: Augment) -> None:
        self.picks[augment.id] = self.picks.get(augment.id, 0) + 1

    def level_of(self, augment_id: str) -> int:
        return self.picks.get(augment_id, 0)

    @property
    def active_ids(self) -> list[str]:
        return [aid for aid, count in self.picks.items() if count > 0]


def run_pipeline(
    grid: list[list[int]],
    cols: int,
    rows: int,
    start: tuple[int, int],
    goal: tuple[int, int],
    build: AugmentBuild,
    rng: random.Random,
) -> AugmentContext:
    """
    Apply every active augment (level > 0) in ALL_AUGMENTS *registry order*
    -- not pick order -- to the generated maze. Registry order is a hard
    contract: every augment's apply() must assume any earlier augment in
    ALL_AUGMENTS may have already mutated ctx.grid/ctx.reserved/ctx.frontier,
    and must fold its own effect on top rather than starting from a
    pristine grid. An augment that places mandatory content must root its
    own search at ctx.frontier (not ctx.start) and advance ctx.frontier to
    wherever its own mandatory chain ends -- see AugmentContext's docstring.
    Final goal placement happens once, centrally, after the whole loop
    (_finalize_goal()), not inside any individual augment.
    """
    ctx = AugmentContext(grid=grid, cols=cols, rows=rows, start=start, goal=goal, rng=rng)
    ctx.reserved = {start, goal}
    ctx.frontier = start
    for augment in ALL_AUGMENTS:
        level = build.level_of(augment.id)
        if level <= 0:
            continue
        ctx.level = level
        augment.apply(ctx)
    _finalize_goal(ctx)
    if ctx.extra.get("twin_goals_active"):
        _resolve_secondary_goal(ctx)
    return ctx


def _finalize_goal(ctx: AugmentContext) -> None:
    """
    Runs once, after every active augment's mandatory content has been
    folded into ctx.frontier -- moves goal placement out of individual
    augments (which used to independently overwrite ctx.goal, silently
    orphaning whichever one didn't run last) into one shared step, so the
    final goal structurally requires the *entire* accumulated gauntlet
    regardless of which augments are active or what order they ran in.

    Runs unconditionally, even when nothing placed mandatory content
    (ctx.frontier == ctx.start) -- in that case ctx.extra["mandatory_gated_cells"]
    is empty, so this degrades to plain teleporter-aware farthest-cell
    placement from ctx.start, same as the no-augment default but now also
    accounting for decorative teleporter shortcuts.

    Uses plain grid-adjacency BFS (maze.farthest_reachable_cell), not a
    real-move walk -- an earlier version tried restricting *traversal*
    itself to the ground-truth reachable set (doors.py's
    sequentially_reachable(), which only ever contains stoppable cells) and
    that was a real, measured bug: the single-hop stoppable-only adjacency
    graph is almost entirely disconnected once mandatory gate cells are
    excluded from it, so the search could barely leave ctx.frontier's own
    small sealed pocket regardless of the maze's actual size (goal depth
    averaged under half the no-augment baseline, sometimes as low as 4
    cells on a 41x41 maze). Fixed by restricting only the *candidates* a
    plain BFS traversal is allowed to land on -- ctx.extra["mandatory_gated_cells"],
    which each mandatory placement OVERWRITES (not unions) with its own
    gated blob/subtree. This is deliberate, not an oversight: every
    mandatory placement after the first is architecturally nested *inside*
    whatever the previous one sealed (it's rooted at ctx.frontier, which
    sits inside that earlier pocket, so pendant_subtree_map() can only ever
    explore within it) -- meaning each new gated set is always a subset of
    the one before it. A union would therefore always collapse to just the
    *first* mandatory augment's region, which would silently stop forcing
    every augment placed after it -- the exact "later augment's mandatory
    content becomes optional" bug ctx.frontier itself exists to prevent, in
    a different shape. Keeping only the latest (innermost) gated set is what
    actually requires the *entire* chain: any cell inside it is physically
    walled off except through every earlier pocket's own entrance too.
    Traversal itself stays a full, always-connected plain BFS -- only the
    "farthest" *answer* is filtered by candidates membership; doors need no
    special handling since a locked door is already grid-open to plain
    adjacency by design (see doors.py's module docstring).

    Unlike doors, a shifting_room.py pocket IS a real, physically-closed
    wall until its pad is triggered -- invisible to plain BFS traversal
    entirely, not just behaviorally gated. Left as-is, a mandatory pad's
    own gated blob would be permanently unvisitable by this function's
    BFS, so `gated` could never actually contain anything the traversal
    reached, and the goal would silently collapse back to ctx.start. Fixed
    by planning against _grid_with_pressure_pads_opened(ctx) instead of
    ctx.grid directly -- every pad is treated as pre-opened for placement
    purposes, on the reasoning that any mandatory pad WILL eventually be
    triggered in real play (the same "assume it'll happen" approximation
    already accepted for a door's key-collection detour, which similarly
    isn't accounted for in this same distance metric).
    """
    tmap = _combined_teleport_map(ctx)
    gated = ctx.extra.get("mandatory_gated_cells")
    planning_grid = _grid_with_pressure_pads_opened(ctx)
    ctx.goal = farthest_reachable_cell(planning_grid, ctx.start, extra_edges=tmap, candidates=gated or None)


def _resolve_secondary_goal(ctx: AugmentContext) -> None:
    """
    Twin Goals' actual placement work -- deferred until after
    _finalize_goal() (called from run_pipeline() right after it,
    conditional on TwinGoalsAugment having set ctx.extra["twin_goals_active"])
    because it needs the *finalized* primary goal as one of its two BFS
    distance anchors, which doesn't exist until that step runs.
    TwinGoalsAugment.apply() itself is a no-op that only sets that flag --
    see twin_goals.py.

    Deliberately NOT constrained by ctx.extra["mandatory_gated_cells"] the
    way the primary goal is -- Twin Goals is shipped mutually exclusive
    with Doors/Teleporters instead (see offer_augment_cards()) precisely
    because an unconstrained secondary goal could otherwise land outside a
    mandatory gate's sealed region, making that gate skippable entirely
    (reach the easy goal, done). Stores the result -- a cell, or None if no
    candidate qualifies (e.g. a maze too small to fit two well-separated
    goals) -- in ctx.extra["secondary_goal"].
    """
    tmap = _combined_teleport_map(ctx)
    planning_grid = _grid_with_pressure_pads_opened(ctx)
    exclude = {ctx.start, ctx.goal} | ctx.reserved
    ctx.extra["secondary_goal"] = secondary_goal_candidate(
        planning_grid, ctx.start, ctx.goal,
        extra_edges=tmap, exclude=exclude,
        min_start_fraction=TWIN_GOAL_MIN_START_DISTANCE_FRACTION,
        min_goal_fraction=TWIN_GOAL_MIN_GOAL_DISTANCE_FRACTION,
        rng=ctx.rng,
    )


def _grid_with_pressure_pads_opened(ctx: AugmentContext) -> list[list[int]]:
    """
    A copy of ctx.grid with every shifting_room.py pad's controlled wall
    segment pre-opened -- see _finalize_goal()'s docstring for why goal
    placement needs to "see through" a wall that's real and closed at
    generation time but guaranteed to eventually open in real play.
    Returns ctx.grid itself, unmutated, when there are no pads at all (the
    common case) rather than an unnecessary copy.
    """
    pads = ctx.extra.get("pressure_pads", [])
    if not pads:
        return ctx.grid
    grid = [row[:] for row in ctx.grid]
    for pad in pads:
        wx, wy = pad.wall_segment
        grid[wy][wx] = 0
    return grid


def nested_local_forbidden(ctx: AugmentContext, current_start: tuple[int, int]) -> set[tuple[int, int]] | None:
    """
    None if `current_start` sits in the openly-reachable main region (not
    yet nested inside any sealed pocket) -- callers should fall back to
    their usual ctx.reserved-based candidate filtering in that case, which
    legitimately needs to reject a candidate that would overlap ANY
    already-placed, separate pocket's entire footprint.

    Otherwise (current_start already sits inside a sealed pocket -- this is
    how a mandatory chain nests deeper, within one augment's own chain or
    across augments), returns the much narrower set candidates should
    avoid: every individual already-placed special cell (teleporter
    entrance/exit, door/key, pressure pad) -- NOT the enclosing pocket's
    entire blob.

    Why the distinction matters: ctx.reserved deliberately includes a
    sealed pocket's *entire* cell closure (not just its special cells), so
    that a *separate*, non-nested placement elsewhere can never overlap it.
    But that same blanket set, applied to a search already rooted *inside*
    that pocket, would reject every single candidate -- the whole point of
    nesting is to further subdivide that same, already-isolated interior,
    not avoid it. A pocket's own boundary already topologically confines a
    nested pendant_subtree_map() search to just its interior (nothing
    outside is plain-grid reachable from inside a sealed pocket), so the
    only genuine remaining risk is colliding with a specific cell some
    other already-placed pair is relying on, which is exactly what this
    narrower set protects against.
    """
    # current_start == ctx.start is always the open main region, never a
    # sealed pocket's interior -- even though ctx.start itself is always a
    # member of ctx.reserved (seeded there by run_pipeline() so no augment
    # ever claims it as one of its own special cells), which would
    # otherwise falsely trip the "nested" branch on literally the very
    # first placement of a run and let it use the far-too-narrow local
    # exclusion set instead of the full ctx.reserved check it actually
    # needs at that point.
    if current_start == ctx.start or current_start not in ctx.reserved:
        return None
    cells: set[tuple[int, int]] = set()
    for pair in ctx.extra.get("teleporters", []):
        cells.add(pair.a)
        cells.add(pair.b)
    for pair in ctx.extra.get("doors", []):
        cells.add(pair.door)
        cells.add(pair.key)
    for pad in ctx.extra.get("pressure_pads", []):
        cells.add(pad.pad)
    return cells


def _combined_teleport_map(ctx: AugmentContext) -> dict[tuple[int, int], tuple[int, int]]:
    """Every teleporter pair placed so far, folded into a map -- see _movement.py's slide_path(teleport=...) hook."""
    tmap: dict[tuple[int, int], tuple[int, int]] = {}
    for pair in ctx.extra.get("teleporters", []):
        tmap[pair.a] = pair.b
        tmap[pair.b] = pair.a
    return tmap


# Twin Goals' secondary-goal search isn't constrained by a mandatory
# gating augment's sealed region the way the primary goal is (see
# _resolve_secondary_goal()'s docstring) -- composing it with Doors/
# Teleporters risks making a mandatory gate skippable entirely. Shipped
# mutually exclusive in v1 rather than attempting full composability;
# true composability (constraining the secondary goal to the same gated
# region) is a possible follow-up once it's been validated to actually
# find a candidate often enough to be worth it.
_MUTUALLY_EXCLUSIVE_AUGMENT_IDS: dict[str, set[str]] = {
    "twin_goals": {"teleporters", "doors"},
    "teleporters": {"twin_goals"},
    "doors": {"twin_goals"},
}


def offer_augment_cards(
    build: AugmentBuild,
    rng: random.Random | None = None,
    count: int = AUGMENT_CARDS_OFFERED,
) -> list[Augment]:
    """
    Cap-aware card offer for the every-AUGMENT_INTERVAL-th modifier break.

    Below MAX_ACTIVE_AUGMENTS distinct active augments: prefer offering
    augments the player doesn't have yet (so picking one grows the active
    set), topped up with already-active ones if there aren't enough
    not-yet-active augments to fill the offer (true immediately at ship
    time -- ALL_AUGMENTS has just 1 entry until more augments are built).
    At or above the cap: every offer is drawn only from already-active
    augments, so a pick necessarily levels one up (mirrors how repeat perk
    picks already stack multiplicatively).

    Not-yet-active augments incompatible with something already active
    (_MUTUALLY_EXCLUSIVE_AUGMENT_IDS) are filtered out of the offer pool
    entirely -- an already-active augment is never filtered this way (it's
    always safe to offer a level-up), only new picks that would create an
    incompatible combination.
    """
    rng = rng if rng is not None else random
    active = set(build.active_ids)
    if len(active) < MAX_ACTIVE_AUGMENTS:
        pool = [
            a for a in ALL_AUGMENTS
            if a.id not in active and not (_MUTUALLY_EXCLUSIVE_AUGMENT_IDS.get(a.id, set()) & active)
        ]
        if len(pool) < count:
            pool = pool + [a for a in ALL_AUGMENTS if a.id in active]
    else:
        pool = [a for a in ALL_AUGMENTS if a.id in active]
    return rng.sample(pool, min(count, len(pool)))


ALL_AUGMENTS: list[Augment] = []
AUGMENTS_BY_ID: dict[str, Augment] = {}

# Deferred import: gating/teleporters.py and gating/doors.py both import
# Augment/AugmentContext/ALL_AUGMENTS from this module, so the registration
# step has to happen down here, after they're defined, not at the top of
# the file (that would be circular).
from maze_game.progression.augments.gating import DoorsAugment, TeleportersAugment  # noqa: E402
from maze_game.progression.augments.shifting_room import ShiftingRoomAugment  # noqa: E402
from maze_game.progression.augments.runtime import FogOfWarAugment, RotatingMazeAugment, PeekAugment  # noqa: E402
from maze_game.progression.augments.twin_goals import TwinGoalsAugment  # noqa: E402

# Order matters for the first three: DoorsAugment must run after
# TeleportersAugment -- a door candidate is verified against the maze's
# already-finalized teleporter map, so a teleporter can never silently
# bypass a door that looked like a genuine cut vertex under plain grid
# adjacency (see doors.py) -- and ShiftingRoomAugment must run after both,
# for the identical reason (see shifting_room.py). runtime/ augments have
# a no-op apply(), so their position in this tuple doesn't affect
# generation at all.
for _augment in (
    TeleportersAugment(), DoorsAugment(), ShiftingRoomAugment(),
    RotatingMazeAugment(), FogOfWarAugment(), PeekAugment(), TwinGoalsAugment(),
):
    ALL_AUGMENTS.append(_augment)
    AUGMENTS_BY_ID[_augment.id] = _augment
del _augment
