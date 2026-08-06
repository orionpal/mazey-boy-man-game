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
hook; an augment's run-time
behaviour (e.g. teleporters.py's contact effect) wires directly into
player.slide_path()/progression/renderer.py instead.

NOTE: with ALL_AUGMENTS currently holding just the one shipped augment
(teleporters), every modifier break necessarily offers a single forced
card until more augments are built -- expected, not a bug.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Any

from maze_game.constants import MAX_ACTIVE_AUGMENTS
from maze_game.progression.augments._movement import farthest_within

AUGMENT_CARDS_OFFERED = 3  # mirrors shop/__init__.py::SHOP_CARDS_OFFERED


class Augment:
    """Base for a maze-generation-time modifier. Concrete augments live in sibling modules (e.g. teleporters.py)."""

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
    tests/progression/augments/test_composition.py). Starts at `start`;
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
    return ctx


def _finalize_goal(ctx: AugmentContext) -> None:
    """
    Runs once, after every active augment's mandatory content has been
    folded into ctx.frontier -- moves goal placement out of individual
    augments (which used to independently overwrite ctx.goal, silently
    orphaning whichever one didn't run last) into one shared step, so the
    final goal structurally requires the *entire* accumulated gauntlet
    regardless of which augments are active or what order they ran in.

    Deliberately a no-op when ctx.frontier is still ctx.start (nobody
    placed mandatory content): preserves the caller's own plain
    farthest_reachable_cell default (see run.py::_begin_maze()) exactly,
    rather than silently switching goal-distance metrics for mazes this
    fix doesn't need to touch.

    Computes the *real*, sequentially-consistent reachable set once (via
    doors.py's own sequentially_reachable(), the same ground-truth check
    every augment's own placement already trusts -- rooted at ctx.start,
    not ctx.frontier, so a mandatory link's own reverse route can't leak
    the search back outside the pocket it just sealed the way rooting
    *at* ctx.frontier would), then finds the farthest cell *from
    ctx.frontier* within that set, minus every mandatory trigger cell
    (_mandatory_gate_cells()) -- via plain grid adjacency
    (farthest_within()), deliberately not a second real-move walk. See
    both helpers' docstrings for why: a mandatory teleporter pair is
    bidirectional and a mandatory door cell is grid-open once its key is
    (correctly) found, so plain "was this ever reachable" membership alone
    isn't enough to stop the search walking back out the same way it came
    in and discovering the unrelated near side.
    """
    if ctx.frontier == ctx.start:
        return
    from maze_game.progression.augments.doors import sequentially_reachable  # deferred: doors.py imports this module

    tmap = _combined_teleport_map(ctx)
    doors = ctx.extra.get("doors", [])
    reachable = sequentially_reachable(ctx.grid, ctx.start, doors, teleport=lambda x, y: tmap.get((x, y)))
    search_allowed = reachable - _mandatory_gate_cells(ctx)
    ctx.goal = farthest_within(ctx.grid, ctx.frontier, search_allowed)


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
    entrance/exit, door/key) -- NOT the enclosing pocket's entire blob.

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
    return cells


def _combined_teleport_map(ctx: AugmentContext) -> dict[tuple[int, int], tuple[int, int]]:
    """Every teleporter pair placed so far, folded into a map -- see _movement.py's slide_path(teleport=...) hook."""
    tmap: dict[tuple[int, int], tuple[int, int]] = {}
    for pair in ctx.extra.get("teleporters", []):
        tmap[pair.a] = pair.b
        tmap[pair.b] = pair.a
    return tmap


def _mandatory_gate_cells(ctx: AugmentContext) -> set[tuple[int, int]]:
    """
    Every cell that's a *mandatory* teleporter/door trigger -- used by
    _finalize_goal() to keep its frontier-rooted farthest-cell search from
    walking back out through one of them. Re-crossing any of these can't
    reveal new territory (the player already necessarily used it to reach
    ctx.frontier), but leaving one open to the search would let it discover
    the vast, unrelated region on the near side of the mandatory chain,
    silently defeating the whole forced-use guarantee. Decorative triggers
    are never excluded -- they don't sit on a sealed boundary (see
    teleporters.py/doors.py's own decorative-placement docstrings), so
    re-crossing one is never a leak.
    """
    cells: set[tuple[int, int]] = set()
    for pair in ctx.extra.get("teleporters", []):
        if pair.mandatory:
            cells.add(pair.a)
            cells.add(pair.b)
    for pair in ctx.extra.get("doors", []):
        if pair.mandatory:
            cells.add(pair.door)
    return cells


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
    """
    rng = rng if rng is not None else random
    active = set(build.active_ids)
    if len(active) < MAX_ACTIVE_AUGMENTS:
        pool = [a for a in ALL_AUGMENTS if a.id not in active]
        if len(pool) < count:
            pool = pool + [a for a in ALL_AUGMENTS if a.id in active]
    else:
        pool = [a for a in ALL_AUGMENTS if a.id in active]
    return rng.sample(pool, min(count, len(pool)))


ALL_AUGMENTS: list[Augment] = []
AUGMENTS_BY_ID: dict[str, Augment] = {}

# Deferred import: teleporters.py/doors.py import Augment/AugmentContext/
# ALL_AUGMENTS from this module, so the registration step has to happen
# down here, after they're defined, not at the top of the file (that would
# be circular).
from maze_game.progression.augments.teleporters import TeleportersAugment  # noqa: E402
from maze_game.progression.augments.doors import DoorsAugment  # noqa: E402

# Order matters: DoorsAugment must run after TeleportersAugment -- a door
# candidate is verified against the maze's already-finalized teleporter
# map, so a teleporter can never silently bypass a door that looked like a
# genuine cut vertex under plain grid adjacency (see doors.py).
for _augment in (TeleportersAugment(), DoorsAugment()):
    ALL_AUGMENTS.append(_augment)
    AUGMENTS_BY_ID[_augment.id] = _augment
del _augment
