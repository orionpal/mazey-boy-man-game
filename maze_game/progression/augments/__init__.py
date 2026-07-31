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
project's existing precedent (shop/items.py: four different item mechanics
get four dedicated LabyrinthRun methods rather than one forced
abstraction; hazards/boss/renderer.py: bespoke draw methods, not a generic
dispatch). Augment.apply() is the only shared hook; a concrete augment's
run-time behaviour (contact effects, rendering) wires directly into
player.slide_path()/progression/renderer.py instead, in its own sibling
module.

ALL_AUGMENTS/AUGMENTS_BY_ID start empty here -- concrete augments (the
first being teleporting squares) register themselves into this registry
from their own module, keeping this file free of forward references to
augments that don't exist yet.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Any

from maze_game.constants import MAX_ACTIVE_AUGMENTS

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
    Mutable bundle threaded through the augment pipeline. `grid`/`goal` may
    be reassigned by an augment's apply() (e.g. teleporters seals off part
    of the grid and moves the goal into the sealed pocket) -- later
    augments in the pipeline must treat these as already-possibly-mutated,
    not the raw generate_maze() output. `reserved` accumulates cells any
    augment has claimed (teleporter pads, sealed-pocket boundaries, ...) so
    later augments and entity spawning (pellets/enemies) can avoid them.
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
    ALL_AUGMENTS may have already mutated ctx.grid/ctx.goal/ctx.reserved,
    and must fold its own effect on top rather than starting from a
    pristine grid.
    """
    ctx = AugmentContext(grid=grid, cols=cols, rows=rows, start=start, goal=goal, rng=rng)
    ctx.reserved = {start, goal}
    for augment in ALL_AUGMENTS:
        level = build.level_of(augment.id)
        if level <= 0:
            continue
        ctx.level = level
        augment.apply(ctx)
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
