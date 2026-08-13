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
a new coat of paint. Linked back to the region above by a "stairs" pair --
mechanically identical to a teleporter pair (step on either cell, warp to
its partner, stop immediately; see player.slide_path()'s existing
`teleport` hook, reused as-is) -- so no new engine mechanic is needed, only
a different name/render for the same warp.

Level scaling: level 1 recarves a couple of floors with one mandatory;
higher levels add more floors and make more of them mandatory (see
MULTI_LEVEL_* constants), each successive mandatory floor nested one level
deeper than the last -- walking into floor N's stairs and searching *from
there* for floor N+1 naturally confines the search to floor N's own,
already-isolated interior (identical nesting trick to teleporters.py).
The *first* mandatory floor is rooted at `ctx.mandatory_frontier`, not
`ctx.start` -- if an earlier gating augment (teleporters, doors) already
placed a mandatory gate, this floor nests behind it instead of ignoring it
(see augments/__init__.py's `AugmentContext.mandatory_frontier` docstring).

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
its boundary -- the stairs pair is the *only* way in, exactly like a
teleporter's mandatory pocket. Once every mandatory floor is placed, this
augment advances the shared `ctx.mandatory_frontier` to the deepest one's
own recarved interior rather than relocating `ctx.goal` itself --
run_pipeline() picks the actual final goal (via farthest_reachable_cell)
once every active augment has had a turn, so finishing the maze is only
possible by walking onto every mandatory floor's `down` stairs in turn
*and* satisfying whatever mandatory gate any other active augment placed,
in registry order. See tests/progression/augments/test_multi_level.py's
"forced-use" tests for the bfs_reachable()-must-fail /
sequentially_reachable()-must-succeed pair that proves this, mirroring the
same standard doors.py's own test suite holds itself to.
"""

from __future__ import annotations

from dataclasses import dataclass

from maze_game.constants import (
    MULTI_LEVEL_FLOOR_COUNT_BASE, MULTI_LEVEL_FLOOR_COUNT_STEP, MULTI_LEVEL_FLOOR_COUNT_MAX,
    MULTI_LEVEL_MANDATORY_COUNT_BASE, MULTI_LEVEL_MANDATORY_COUNT_STEP,
    MULTI_LEVEL_FLOOR_MIN_SIZE, MULTI_LEVEL_FLOOR_MAX_SIZE,
    MULTI_LEVEL_PLACEMENT_MAX_ATTEMPTS,
)
from maze_game.maze import is_stoppable_cell, bfs_reachable
from maze_game.progression.augments import Augment, AugmentContext
from maze_game.progression.augments._movement import pendant_subtree_map, seal_pocket
from maze_game.progression.augments.doors import sequentially_reachable

_PASSAGE_STEPS = ((0, -2), (0, 2), (-2, 0), (2, 0))


@dataclass(frozen=True)
class FloorLink:
    """
    A stairs pair linking a cell in the shallower region (`down`) to a cell
    inside the recarved floor it leads to (`up`). `floor` is the 1-based
    nesting depth of the floor `up` sits on.
    """

    down: tuple[int, int]
    up: tuple[int, int]
    mandatory: bool
    color_index: int
    floor: int


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
        current_start = ctx.mandatory_frontier
        for depth in range(1, mandatory_count + 1):
            link = _place_floor(
                ctx, current_start, tmap, doors,
                mandatory=True, depth=depth, color_index=depth - 1, committed=floors,
            )
            if link is None:
                break  # graceful degradation -- fewer mandatory floors than the formula asked for
            floors.append(link)
            current_start = link.up

        if floors:
            # Advance the shared cross-augment checkpoint rather than
            # relocating ctx.goal ourselves -- see run_pipeline()'s
            # docstring. MultiLevelAugment runs last in the registry, but
            # doesn't get to assume it's the last *active* gating augment
            # (the player could be at a lower level for a later-added
            # augment, or none at all) -- so it defers final goal placement
            # exactly the same way teleporters/doors now do.
            ctx.mandatory_frontier = current_start

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
    scratch, and link it to `current_start`'s region with a stairs pair --
    verified with the full sequentially_reachable() (folding in every
    already-placed door's key-collection order and every teleporter link)
    before committing, the same standard doors.py's own placement holds
    itself to. The reachability target checked is `current_start`
    (mandatory) or `ctx.mandatory_frontier` (decorative), not `ctx.goal` --
    see the inline comment above the check for why.

    Mutates ctx.grid/ctx.reserved in place on success. Returns None if no
    candidate works out (graceful degradation).

    Passes every already-placed door's cell as `pendant_subtree_map()`'s
    `blocked` set for the identical reason doors.py's own nested mandatory
    search does (see its docstring): a door's cell deliberately stays
    grid-open, so `current_start` sitting behind one -- e.g. this floor
    nesting behind a mandatory door via an inherited `ctx.mandatory_frontier`
    -- would otherwise let this search's `order` leak back out through it,
    silently pulling in already-reserved territory (that door's own cell,
    its key, ...) as if it were fresh local floor territory. That territory
    then also wouldn't get caught by the `subtree[c] & (ctx.reserved - local)`
    overlap check just below, since a leaked cell counts as "local" once
    it's in `order` -- so it could end up inside `blob` and get silently
    recarved, corrupting an already-placed door or key.
    """
    blocked_doors = frozenset(pair.door for pair in doors)
    order, subtree, _parent = pendant_subtree_map(ctx.grid, current_start, blocked=blocked_doors)
    # See teleporters.py::_place_mandatory_pair's identical line for why:
    # current_start's own local territory is necessarily already in
    # ctx.reserved (it's the pocket the previous chain step just sealed),
    # so it has to be subtracted back out here or nesting a mandatory floor
    # inside it could never find a candidate. Cells belonging to *other*
    # (non-ancestor) pockets stay excluded via the subtree-overlap check
    # below, same as before.
    local = set(order)
    forbidden = (ctx.reserved - local) | {current_start}
    candidates = [
        c for c in order
        if c != current_start and c not in forbidden and not (subtree[c] & (ctx.reserved - local))
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

    for _ in range(MULTI_LEVEL_PLACEMENT_MAX_ATTEMPTS):
        if not pool:
            return None
        chosen = ctx.rng.choice(pool)
        pool = [c for c in pool if c != chosen]
        blob = subtree[chosen]

        sealed_grid = seal_pocket(ctx.grid, blob)
        floor_grid = _recarve_blob(sealed_grid, blob, ctx.rng)

        # Same local-territory subtraction as `forbidden`/`candidates` above,
        # and for the identical reason: nesting a floor inside a pocket a
        # previous chain step already reserved (its own blob + down/up) must
        # not treat that same territory as off-limits to itself, or every
        # down/up candidate here is pre-excluded and nesting past the first
        # mandatory floor silently degrades to 0 every time. But the local
        # subtraction alone would also un-reserve an *already-placed*
        # stairs cell sitting inside this same local territory (e.g. the
        # parent floor's own `down`/`up`) -- explicitly re-excluding every
        # committed link's cells (plus current_start, this search's own
        # entry point) keeps stairs cells from ever colliding.
        used_stairs = {c for link in committed for c in (link.down, link.up)} | {current_start}
        forbidden_for_stairs = (ctx.reserved - local) | used_stairs
        after = bfs_reachable(floor_grid, current_start)
        down_candidates = [c for c in after if c not in forbidden_for_stairs and is_stoppable_cell(floor_grid, *c)]
        up_candidates = [c for c in blob if c not in forbidden_for_stairs and is_stoppable_cell(floor_grid, *c)]
        if not down_candidates or not up_candidates:
            continue

        down = ctx.rng.choice(down_candidates)
        up = ctx.rng.choice(up_candidates)

        tentative_tmap = dict(tmap)
        for link in committed:
            tentative_tmap[link.down] = link.up
            tentative_tmap[link.up] = link.down
        tentative_tmap[down] = up
        tentative_tmap[up] = down

        reachable = sequentially_reachable(
            floor_grid, ctx.start, doors, teleport=lambda x, y: tentative_tmap.get((x, y)),
        )
        # A mandatory floor protects its own inherited chain frontier
        # (current_start -- which IS ctx.mandatory_frontier for the first
        # mandatory floor, or a deeper one nested by this same augment's
        # own earlier iterations); a decorative floor -- always rooted at
        # ctx.start, so current_start itself is a trivial check -- instead
        # protects whatever ctx.mandatory_frontier currently holds, since
        # that's the established mandatory chain it must not sever. Neither
        # checks ctx.goal: it isn't final until run_pipeline() finishes.
        protect_target = current_start if mandatory else ctx.mandatory_frontier
        if up not in reachable or protect_target not in reachable:
            continue  # this stairs pair -- or sealing its pocket -- broke solvability somewhere; try another

        ctx.grid = floor_grid
        ctx.reserved |= blob | {down, up}
        return FloorLink(down=down, up=up, mandatory=mandatory, color_index=color_index, floor=depth)

    return None
