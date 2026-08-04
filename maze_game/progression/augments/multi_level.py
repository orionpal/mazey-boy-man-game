"""
multi_level.py
---------------
The third maze augment: multi-level mazes. A "floor" is a pocket of the
maze -- selected and sealed off exactly like teleporters.py's pockets
(pendant_subtree_map() + seal_pocket()) -- whose *own* internal layout is
then discarded and recarved from scratch (_recarve_blob()), rather than
reusing whatever generate_maze() originally carved there. That's the one
thing this augment adds that teleporters/doors don't: a floor reads as a
genuinely different level, not the parent maze's leftover interior wearing
a new coat of paint. (progression/renderer.py additionally crops the
camera to a floor's own bounding box while the player is on it, so it also
*renders* at full-viewport scale instead of squeezed into its real small
footprint -- see renderer.py's Layout docstring.)

Linked back to the region above by TWO one-way warps, not one bidirectional
pair -- `entrance` (parent cell) -> `floor_start` (floor cell) going up,
and a *separately placed* `floor_exit` (floor cell) -> `return_landing`
(parent cell) coming back down, which need not be anywhere near `entrance`.
Both parent-side cells (`entrance` and `return_landing`) are rendered from
the moment the floor exists, before the player has ever taken the stairs,
so there's always a way to see where a floor's down-stairs will let you
back out, not just where its up-stairs are. Mechanically this is still
just two ordinary entries in the same `_teleport_map` a real teleporter
uses (see player.slide_path()'s existing `teleport` hook) -- nothing in
that hook requires a pair to be symmetric, so no new engine mechanic is
needed for the asymmetry, only two map entries instead of one.

Level scaling: level 1 recarves a couple of floors with one mandatory;
higher levels add more floors and make more of them mandatory (see
MULTI_LEVEL_* constants), each successive mandatory floor nested one level
deeper than the last -- walking into floor N's stairs and searching *from
there* for floor N+1 naturally confines the search to floor N's own,
already-isolated interior (identical nesting trick to teleporters.py).

Must run after TeleportersAugment and DoorsAugment in
augments/__init__.py's ALL_AUGMENTS registry -- a floor candidate is
verified against the maze's already-finalized teleporter map *and* its
door/key state (via doors.py's own sequentially_reachable(), the
ground-truth "can the player actually get there in some valid
key-collection order" check), so a stairs pair can never silently rely on
solvability an already-placed door or teleporter has actually made
contingent.

A floor's candidate pocket is additionally required to *not* contain any
already-reserved cell anywhere in its closure (not just at the root, unlike
teleporters/doors) -- recarving rewrites every internal wall of the pocket,
so an existing teleporter pad or door/key cell caught inside it could have
its stoppable-ness silently changed by the recarve, breaking an
already-placed, already-verified augment. Sealing a pocket alone (what
teleporters/doors do) never has this problem, since it never touches
anything *inside* the pocket's own interior.

**Forced-use guarantee.** A mandatory floor's pocket is sealed with *no*
kept-open crossing at all (unlike doors.py's seal_pocket(..., keep_open=)),
so plain grid adjacency (bfs_reachable/shortest_path) can never reach past
its boundary -- `entrance` is the *only* way in, exactly like a
teleporter's mandatory pocket. This module composes with the other two via
the shared ctx.frontier (see augments/__init__.py's AugmentContext
docstring): a mandatory floor's own search is rooted at ctx.frontier (not
ctx.start), and advances ctx.frontier to `floor_start` on success, so
whatever runs next in the pipeline nests its own mandatory content behind
this floor too, instead of independently claiming the goal and silently
orphaning it (a real bug the frontier mechanism fixes -- see
docs/progression.md's Multi-Level Mazes section). The final goal is placed
once, centrally, in run_pipeline()'s _finalize_goal(), only after every
active augment's mandatory content -- across all three augments, in
whatever combination the player picked -- has been folded into the
frontier chain. See tests/progression/augments/test_multi_level.py's
"forced-use" tests and test_composition.py for the
bfs_reachable()-must-fail / sequentially_reachable()-must-succeed pairs
that prove this, mirroring the same standard doors.py's own test suite
holds itself to.
"""

from __future__ import annotations

from dataclasses import dataclass

from maze_game.constants import (
    MULTI_LEVEL_FLOOR_COUNT_BASE, MULTI_LEVEL_FLOOR_COUNT_STEP, MULTI_LEVEL_FLOOR_COUNT_MAX,
    MULTI_LEVEL_MANDATORY_COUNT_BASE, MULTI_LEVEL_MANDATORY_COUNT_STEP,
    MULTI_LEVEL_FLOOR_MIN_SIZE, MULTI_LEVEL_FLOOR_MAX_SIZE,
    MULTI_LEVEL_PLACEMENT_MAX_ATTEMPTS, MULTI_LEVEL_RETURN_NEAR_RADIUS,
)
from maze_game.maze import is_stoppable_cell
from maze_game.progression.augments import Augment, AugmentContext, nested_local_forbidden
from maze_game.progression.augments._movement import pendant_subtree_map, real_move_reachable, seal_pocket
from maze_game.progression.augments.doors import sequentially_reachable

_PASSAGE_STEPS = ((0, -2), (0, 2), (-2, 0), (2, 0))


@dataclass(frozen=True)
class FloorLink:
    """
    Two one-way stairs warps linking a parent region to a recarved floor:
    `entrance` (parent cell) -> `floor_start` (floor cell) going up, and
    `floor_exit` (floor cell) -> `return_landing` (parent cell) coming back
    down. `return_landing` is deliberately a *different* parent cell than
    `entrance` in general (see module docstring) -- both are placed and
    rendered together so the player can see, before ever taking the
    stairs, both where a floor's entrance is and where its exit will let
    them back out. `blob` is the floor's own cell set (used by
    renderer.py to crop the camera to it). `floor` is the 1-based nesting
    depth of the floor `floor_start` sits on.
    """

    entrance: tuple[int, int]
    floor_start: tuple[int, int]
    floor_exit: tuple[int, int]
    return_landing: tuple[int, int]
    mandatory: bool
    color_index: int
    floor: int
    blob: frozenset[tuple[int, int]]


class MultiLevelAugment(Augment):
    id = "multi_level"
    name = "Multi-Level Mazes"
    description = (
        "A pocket of the maze is rebuilt as its own level, reachable only by a linked staircase. "
        "Higher levels add more floors, and more of them mandatory to reach the goal."
    )

    def apply(self, ctx: AugmentContext) -> None:
        floor_count = min(
            MULTI_LEVEL_FLOOR_COUNT_BASE + MULTI_LEVEL_FLOOR_COUNT_STEP * (ctx.level - 1),
            MULTI_LEVEL_FLOOR_COUNT_MAX,
        )
        mandatory_count = min(
            MULTI_LEVEL_MANDATORY_COUNT_BASE + MULTI_LEVEL_MANDATORY_COUNT_STEP * (ctx.level - 1),
            floor_count,
        )
        tmap = _existing_teleport_map(ctx)
        doors = ctx.extra.get("doors", [])

        floors: list[FloorLink] = []
        current_start = ctx.frontier
        for depth in range(1, mandatory_count + 1):
            link = _place_floor(
                ctx, current_start, tmap, doors,
                mandatory=True, depth=depth, color_index=depth - 1, committed=floors,
            )
            if link is None:
                break  # graceful degradation -- fewer mandatory floors than the formula asked for
            floors.append(link)
            # _place_floor() already advanced ctx.frontier to floor_start
            # for a mandatory floor -- root the next one there, nesting it
            # inside this floor's own recarved interior.
            current_start = ctx.frontier

        # Decoratives are optional side content in the broadly-reachable
        # main region, so they're deliberately rooted at ctx.start (the
        # full main region), not ctx.frontier (the mandatory chain's own,
        # narrower end) -- mirrors teleporters.py's own decoratives, which
        # root at bfs_reachable(ctx.grid, ctx.start) for the same reason.
        decorative_count = floor_count - len(floors)
        for i in range(decorative_count):
            link = _place_floor(
                ctx, ctx.start, tmap, doors,
                mandatory=False, depth=1, color_index=len(floors), committed=floors,
            )
            if link is None:
                break  # graceful degradation -- fewer decorative floors than requested
            floors.append(link)

        ctx.extra["floors"] = floors


def _existing_teleport_map(ctx: AugmentContext) -> dict[tuple[int, int], tuple[int, int]]:
    """The already-finalized teleporter map (if TeleportersAugment ran first), for the real-move reachability checks below."""
    tmap: dict[tuple[int, int], tuple[int, int]] = {}
    for pair in ctx.extra.get("teleporters", []):
        tmap[pair.a] = pair.b
        tmap[pair.b] = pair.a
    return tmap


def _blob_geometric_neighbors(cx: int, cy: int, blob: set) -> list[tuple[int, int]]:
    """Every blob cell 2 apart from (cx, cy) in a cardinal direction -- geometric adjacency, ignoring current wall state (recarving discards it)."""
    return [(cx + dx, cy + dy) for dx, dy in _PASSAGE_STEPS if (cx + dx, cy + dy) in blob]


def _recarve_blob(grid: list[list[int]], blob: set, rng) -> list[list[int]]:
    """
    Discard the pocket's original internal layout and carve a fresh
    spanning tree over just its own cells (a plain backtracker, restricted
    to `blob`'s own geometric adjacency instead of the full grid) -- this is
    what makes a floor read as a genuinely different level rather than the
    parent maze's leftover interior. Only ever opens/closes a wall segment
    whose *both* endpoints are in `blob`, so nothing outside it is touched.

    `blob`'s own geometric-adjacency graph is guaranteed connected: `blob`
    is a pendant subtree of the *original* grid's passage graph (built only
    from already-open, hence geometrically-adjacent, edges), so the tree
    that produced it is already a connected subgraph of blob's full
    geometric-adjacency graph.

    Returns a new grid; does not mutate the input.
    """
    recarved = [row[:] for row in grid]
    for cx, cy in blob:
        for nx, ny in _blob_geometric_neighbors(cx, cy, blob):
            wx, wy = (cx + nx) // 2, (cy + ny) // 2
            recarved[wy][wx] = 1  # reset to wall; selectively reopened below

    root = next(iter(blob))
    visited = {root}
    active = [root]
    while active:
        cx, cy = active[-1]
        neighbours = [n for n in _blob_geometric_neighbors(cx, cy, blob) if n not in visited]
        if not neighbours:
            active.pop()
            continue
        rng.shuffle(neighbours)
        nx, ny = neighbours[0]
        wx, wy = (cx + nx) // 2, (cy + ny) // 2
        recarved[wy][wx] = 0
        visited.add((nx, ny))
        active.append((nx, ny))

    return recarved


def _place_floor(
    ctx: AugmentContext,
    current_start: tuple[int, int],
    tmap: dict[tuple[int, int], tuple[int, int]],
    doors: list,
    mandatory: bool,
    depth: int,
    color_index: int,
    committed: list[FloorLink],
) -> FloorLink | None:
    """
    Pick a pendant subtree of `current_start`'s BFS tree sized in
    [MULTI_LEVEL_FLOOR_MIN_SIZE, MULTI_LEVEL_FLOOR_MAX_SIZE] (falling back
    to the smallest subtree at least that big, same fallback shape as
    teleporters._place_mandatory_pair), whose closure contains no
    already-reserved cell, seal its boundary, recarve its interior from
    scratch, and link it to `current_start`'s region with TWO one-way
    stairs warps -- an up trip (entrance -> floor_start) and a separately
    placed down trip (floor_exit -> return_landing) -- each verified with
    the full sequentially_reachable() (folding in every already-placed
    door's key-collection order and every teleporter/floor link) before
    committing, the same standard doors.py's own placement holds itself to.

    On success for a *mandatory* floor, advances ctx.frontier to
    floor_start, so whatever the pipeline places next nests behind this
    floor too (see augments/__init__.py's AugmentContext docstring).
    Mutates ctx.grid/ctx.reserved(/ctx.frontier) in place on success.
    Returns None if no candidate works out (graceful degradation).
    """
    order, subtree, _parent = pendant_subtree_map(ctx.grid, current_start)
    local_forbidden = nested_local_forbidden(ctx, current_start)
    avoid = local_forbidden if local_forbidden is not None else ctx.reserved
    # nested_local_forbidden() only knows about ctx.extra["floors"], which
    # this augment's own apply() doesn't write until every floor in this
    # call is placed -- fold in `committed` (this call's own already-placed
    # floors) directly so a still-in-progress mandatory chain can't
    # re-select or recarve over one of its own earlier links' cells.
    for link in committed:
        avoid = avoid | {link.entrance, link.floor_start, link.floor_exit, link.return_landing}
    candidates = [
        c for c in order
        if c != current_start and c not in avoid and not (subtree[c] & avoid)
    ]
    if not candidates:
        return None

    in_range = [c for c in candidates if MULTI_LEVEL_FLOOR_MIN_SIZE <= len(subtree[c]) <= MULTI_LEVEL_FLOOR_MAX_SIZE]
    if in_range:
        pool = in_range
    else:
        total = len(order)
        big_enough = [
            c for c in candidates
            if MULTI_LEVEL_FLOOR_MIN_SIZE <= len(subtree[c]) and len(subtree[c]) <= max(total // 2, MULTI_LEVEL_FLOOR_MIN_SIZE)
        ]
        if not big_enough:
            return None
        smallest = min(len(subtree[c]) for c in big_enough)
        pool = [c for c in big_enough if len(subtree[c]) == smallest]

    base_tmap = dict(tmap)
    for link in committed:
        base_tmap[link.entrance] = link.floor_start
        base_tmap[link.floor_exit] = link.return_landing

    for _ in range(MULTI_LEVEL_PLACEMENT_MAX_ATTEMPTS):
        if not pool:
            return None
        chosen = ctx.rng.choice(pool)
        pool = [c for c in pool if c != chosen]
        blob = subtree[chosen]

        sealed_grid = seal_pocket(ctx.grid, blob)
        floor_grid = _recarve_blob(sealed_grid, blob, ctx.rng)

        # Plain grid adjacency alone isn't enough here: a door is a
        # behavioral gate, not a real wall (see doors.py's own docstring),
        # so if current_start sits behind an already-placed mandatory door,
        # bfs_reachable() would happily walk straight back through that
        # (grid-open) door cell and discover the near side too -- letting
        # `entrance` land somewhere that doesn't actually require the door
        # at all, defeating the nesting this whole chain relies on. Locking
        # every already-placed mandatory door for this one lookup confines
        # `after` to the region genuinely nested behind whatever's already
        # been established, mirroring _finalize_goal()'s same concern.
        mandatory_door_cells = {pair.door for pair in doors if pair.mandatory}
        after = real_move_reachable(floor_grid, current_start, door_locked=lambda x, y: (x, y) in mandatory_door_cells)
        entrance_candidates = [c for c in after if c not in avoid and is_stoppable_cell(floor_grid, *c)]
        floor_start_candidates = [c for c in blob if c not in avoid and is_stoppable_cell(floor_grid, *c)]
        if not entrance_candidates or not floor_start_candidates:
            continue

        entrance = ctx.rng.choice(entrance_candidates)
        floor_start = ctx.rng.choice(floor_start_candidates)

        up_tmap = dict(base_tmap)
        up_tmap[entrance] = floor_start
        up_reachable = sequentially_reachable(floor_grid, ctx.start, doors, teleport=lambda x, y: up_tmap.get((x, y)))
        if floor_start not in up_reachable or ctx.frontier not in up_reachable:
            continue  # this pocket -- or its entrance -- broke solvability somewhere; try another

        # Up trip is sound; now place the separate down trip. floor_exit
        # must differ from floor_start, return_landing from entrance --
        # they don't need to be reachable from each other via any
        # particular path, just both need to genuinely exist.
        floor_exit_candidates = [c for c in floor_start_candidates if c != floor_start]
        return_landing_candidates = [c for c in entrance_candidates if c != entrance]
        if not floor_exit_candidates or not return_landing_candidates:
            continue  # not enough distinct stoppable cells for a separate down trip; try a different pocket

        floor_exit = ctx.rng.choice(floor_exit_candidates)
        near = [
            c for c in return_landing_candidates
            if max(abs(c[0] - entrance[0]), abs(c[1] - entrance[1])) <= MULTI_LEVEL_RETURN_NEAR_RADIUS
        ]
        return_landing = ctx.rng.choice(near if near else return_landing_candidates)

        full_tmap = dict(up_tmap)
        full_tmap[floor_exit] = return_landing
        reachable = sequentially_reachable(floor_grid, ctx.start, doors, teleport=lambda x, y: full_tmap.get((x, y)))
        if floor_start not in reachable or ctx.frontier not in reachable:
            continue  # adding the down trip somehow broke something already established; try again

        ctx.grid = floor_grid
        ctx.reserved |= blob | {entrance, floor_start, floor_exit, return_landing}
        if mandatory:
            ctx.frontier = floor_start
        return FloorLink(
            entrance=entrance, floor_start=floor_start, floor_exit=floor_exit, return_landing=return_landing,
            mandatory=mandatory, color_index=color_index, floor=depth, blob=frozenset(blob),
        )

    return None
