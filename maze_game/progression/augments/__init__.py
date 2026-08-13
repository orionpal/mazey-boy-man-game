"""
augments/__init__.py
---------------------
Maze augments: generation-time modifiers (teleporting squares, and later
multi-level mazes, shifting maze, reverse controls, lights out -- see
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
from maze_game.progression.augments._movement import real_move_farthest_cell

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
    the grid) -- later augments in the pipeline must treat this as
    already-possibly-mutated, not the raw generate_maze() output. `reserved`
    accumulates cells any augment has claimed (teleporter pads, door/key
    cells, sealed-pocket boundaries, ...) so later augments and entity
    spawning (pellets/hazards) can avoid them.

    `goal` is *not* reassigned by individual augments any more -- see
    `mandatory_frontier` below and `run_pipeline()`'s single relocation step
    at the end of the pipeline, which is what actually owns final goal
    placement now.

    `mandatory_frontier` is the shared, cross-augment "you must have gotten
    this far for real" checkpoint: every gating augment (teleporters, doors,
    multi-level) that places at least one *mandatory* gate roots its own
    mandatory-chain search at whatever `mandatory_frontier` currently holds
    (not blindly at `start`), and advances it to its own chain's endpoint
    once done -- so a second active gating augment necessarily nests its
    mandatory gate(s) *behind* the first one's, instead of both
    independently gating the same original goal (which is what let a
    Teleporters placement strand DoorsAugment at 0 mandatory doors: see
    `run_pipeline()`'s docstring for the full story). Verification checks
    inside each augment's placement helpers use this same field (or the
    `current_start` parameter threaded from it) as the "must remain
    reachable" target instead of `ctx.goal`, since `ctx.goal` isn't final
    until the whole pipeline completes.
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
    mandatory_frontier: tuple[int, int] = (0, 0)


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
    ALL_AUGMENTS may have already mutated ctx.grid/ctx.reserved/
    ctx.mandatory_frontier, and must fold its own effect on top rather than
    starting from a pristine grid.

    **Final goal placement is deferred to here, once, after every augment
    has run** -- individual augments no longer reassign ctx.goal themselves.
    Playtesting found a maze where a Teleporters placement let the goal
    (moved by TeleportersAugment into its own sealed pocket) become invisible
    to DoorsAugment's plain-grid pocket search, silently degrading it to 0
    mandatory doors -- Doors was "active" but the maze never actually
    required opening one. The fix: every gating augment now nests its
    mandatory chain onto the shared `ctx.mandatory_frontier` (starting at
    `start`) instead of independently searching for a pocket that happens to
    contain whatever `ctx.goal` currently is, and advances that frontier to
    its own chain's endpoint instead of relocating the goal mid-pipeline.
    Once every active augment has had a turn, the true goal is the
    *real-movement* farthest cell from the final frontier -- guaranteeing
    the player must pass every active gating augment's mandatory gate, each
    nested inside the last, to reach it. If no active augment placed a
    mandatory gate, the frontier never moves off `start` and the
    caller-supplied `goal` is left untouched.

    **This last step has to be movement-aware too, not plain grid-BFS.**
    An earlier version used `maze.farthest_reachable_cell()` (plain grid
    adjacency) here, and that was its own instance of the same bug class
    this function's docstring already describes: a locked door's cell
    stays grid-open by design (see doors.py), so a plain-grid walk from the
    frontier could step right back out through it into the rest of the
    already-generated maze and land the goal somewhere reachable without
    ever needing a key. Fixed with `real_move_farthest_cell()`
    (`_movement.py`), the same `slide_path()`-state-graph BFS technique
    `real_move_reachable()` already uses for placement-time verification,
    called with `door_locked` covering every placed door (so it can never
    grid-walk back out through one) and no teleport map at all (every
    gating pocket's boundary is otherwise fully re-walled -- see
    teleporters.py/multi_level.py's `seal_pocket()` calls -- so the only
    way back out of one would be its own teleport/stairs link, which this
    deliberately doesn't offer). That confines the search to exactly the
    territory only reachable *after* passing every gate already passed to
    reach the frontier, so the chosen goal keeps that property too.
    """
    ctx = AugmentContext(grid=grid, cols=cols, rows=rows, start=start, goal=goal, rng=rng)
    ctx.reserved = {start, goal}
    ctx.mandatory_frontier = start
    for augment in ALL_AUGMENTS:
        level = build.level_of(augment.id)
        if level <= 0:
            continue
        ctx.level = level
        augment.apply(ctx)
    if ctx.mandatory_frontier != start:
        door_cells = {pair.door for pair in ctx.extra.get("doors", [])}
        door_locked = (lambda x, y: (x, y) in door_cells) if door_cells else None
        ctx.goal = real_move_farthest_cell(ctx.grid, ctx.mandatory_frontier, door_locked=door_locked)
    return ctx


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
from maze_game.progression.augments.multi_level import MultiLevelAugment  # noqa: E402

# Order matters: DoorsAugment must run after TeleportersAugment -- a door
# candidate is verified against the maze's already-finalized teleporter
# map, so a teleporter can never silently bypass a door that looked like a
# genuine cut vertex under plain grid adjacency (see doors.py). MultiLevelAugment
# must run after both -- a floor candidate is verified against the maze's
# already-finalized teleporter map *and* door/key state (see multi_level.py).
for _augment in (TeleportersAugment(), DoorsAugment(), MultiLevelAugment()):
    ALL_AUGMENTS.append(_augment)
    AUGMENTS_BY_ID[_augment.id] = _augment
del _augment
