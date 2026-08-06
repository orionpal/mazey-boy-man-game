"""
shifting_room.py
-----------------
The third gating augment: pressure pads that shift maze connectivity at
*runtime* -- unlike teleporters.py/gating/doors.py, which only ever mutate
the grid once, at generation time. A pocket is sealed *completely* (a real
wall, not a behavioral gate the way a locked door is) except for one
boundary crossing, which stays closed until the player's pad is triggered
-- one-shot (opens permanently, no toggle-back), and fires the instant the
player slides *over* the pad, not only if they stop there (see
player.slide_path()'s pressure_pad hook, and progression/run.py's
LabyrinthRun._trigger_pressure_pad()).

Being a real (not behavioral) wall until triggered is what makes this
augment simpler to place than doors.py's locked-door mechanism, despite
being newer territory (a runtime grid mutation): every existing
generation-time helper (bfs_reachable, real_move_reachable,
sequentially_reachable) already treats a still-closed pocket as plain
unreachable, with no special-casing needed the way a locked-but-grid-open
door cell needs. The one place that DOES need special handling is
planning code that computes something ahead of the player actually
triggering a pad (goal placement, par-time estimation) -- see
augments/__init__.py's _grid_with_pressure_pads_opened() and
progression/run.py's own par-time computation, both of which treat a
mandatory pad as pre-opened for planning purposes, the same class of
approximation already accepted for doors (whose own par-time estimate
doesn't account for the detour needed to fetch a key either).

Composes with other augments via the shared ctx.frontier (see
augments/__init__.py's AugmentContext docstring), exactly like
teleporters.py/doors.py -- this module's mandatory chain is rooted at
ctx.frontier and advances it to a cell independently proven to be behind
the newly-sealed pocket. Must run after TeleportersAugment/DoorsAugment in
augments/__init__.py's ALL_AUGMENTS registry, for the same reason doors.py
must run after teleporters.py: placement is verified against the maze's
already-finalized teleporter map and door list via doors.py's
sequentially_reachable().

Level scaling: level 1 places a couple of pads with only one mandatory;
higher levels add more pads and make more of them mandatory (see SHIFT_*
constants), each successive mandatory pad nested one pocket deeper than
the last.
"""

from __future__ import annotations

from dataclasses import dataclass

from maze_game.constants import (
    SHIFT_PAD_COUNT_BASE, SHIFT_PAD_COUNT_STEP, SHIFT_PAD_COUNT_MAX,
    SHIFT_MANDATORY_COUNT_BASE, SHIFT_MANDATORY_COUNT_STEP,
    SHIFT_POCKET_MIN_SIZE, SHIFT_POCKET_MAX_SIZE,
    SHIFT_PLACEMENT_MAX_ATTEMPTS,
)
from maze_game.maze import bfs_reachable, is_stoppable_cell
from maze_game.progression.augments import Augment, AugmentContext, nested_local_forbidden
from maze_game.progression.augments.gating._movement import pendant_subtree_map, seal_pocket, boundary_crossings
from maze_game.progression.augments.gating.doors import sequentially_reachable


@dataclass(frozen=True)
class PressurePad:
    pad: tuple[int, int]            # stoppable cell; sliding over it triggers the shift
    wall_segment: tuple[int, int]   # the wall-grid cell that opens, permanently, once triggered
    mandatory: bool
    color_index: int


class ShiftingRoomAugment(Augment):
    id = "shifting_room"
    name = "Shifting Room"
    description = (
        "Step on a pressure pad to permanently open a hidden wall elsewhere in the maze. "
        "Higher levels add more pads, and more of them mandatory to reach the goal."
    )

    def apply(self, ctx: AugmentContext) -> None:
        pad_count = min(
            SHIFT_PAD_COUNT_BASE + SHIFT_PAD_COUNT_STEP * (ctx.level - 1),
            SHIFT_PAD_COUNT_MAX,
        )
        mandatory_count = min(
            SHIFT_MANDATORY_COUNT_BASE + SHIFT_MANDATORY_COUNT_STEP * (ctx.level - 1),
            pad_count,
        )
        tmap = _existing_teleport_map(ctx)
        doors = ctx.extra.get("doors", [])

        pads: list[PressurePad] = []
        current_start = ctx.frontier
        for i in range(mandatory_count):
            pad = _place_mandatory_pad(ctx, current_start, tmap, doors, pads, color_index=i)
            if pad is None:
                break  # graceful degradation -- fewer mandatory pads than the formula asked for
            pads.append(pad)
            # _place_mandatory_pad() already advanced ctx.frontier to a
            # verified cell inside the newly-sealed pocket -- root the next
            # mandatory pad there, same reasoning as doors.py's own chain.
            current_start = ctx.frontier

        decorative_count = pad_count - len(pads)
        mandatory_pads = list(pads)
        pads.extend(_place_decorative_pads(ctx, tmap, doors, mandatory_pads, decorative_count, start_index=len(pads)))

        ctx.extra["pressure_pads"] = pads


def _existing_teleport_map(ctx: AugmentContext) -> dict[tuple[int, int], tuple[int, int]]:
    """The already-finalized teleporter map, for the real-move reachability checks below (mirrors doors.py's identical helper)."""
    tmap: dict[tuple[int, int], tuple[int, int]] = {}
    for pair in ctx.extra.get("teleporters", []):
        tmap[pair.a] = pair.b
        tmap[pair.b] = pair.a
    return tmap


def _opened_for_planning(grid: list[list[int]], pads: list[PressurePad]) -> list[list[int]]:
    """
    A copy of `grid` with every pad's controlled wall segment pre-opened --
    for planning/verification purposes only (mirrors
    augments/__init__.py's _grid_with_pressure_pads_opened(), which does
    the same thing for goal placement). Needed because ctx.frontier, once
    a mandatory pad has been placed, sits *behind a real wall*: plain/
    real-move reachability from ctx.start can never reach it in the actual
    (un-opened) grid, so any check that needs to confirm "does this new
    placement still leave ctx.frontier reachable *once its own gate
    eventually opens*" has to reason against this pre-opened planning grid
    instead of the real one.
    """
    if not pads:
        return grid
    opened = [row[:] for row in grid]
    for pad in pads:
        wx, wy = pad.wall_segment
        opened[wy][wx] = 0
    return opened


def _place_mandatory_pad(
    ctx: AugmentContext,
    current_start: tuple[int, int],
    tmap: dict[tuple[int, int], tuple[int, int]],
    doors: list,
    committed: list[PressurePad],
    color_index: int,
) -> PressurePad | None:
    """
    Pick a pendant subtree of `current_start`'s BFS tree, seal its entire
    boundary (seal_pocket() with no keep_open -- a real wall all the way
    around, unlike teleporters/doors which leave one crossing open), then
    designate one of the crossings seal_pocket() just closed as this pad's
    wall_segment.

    Place the pad itself on a stoppable cell within the *true* reachable
    region (doors.py's sequentially_reachable(), accounting for every
    already-placed teleporter and door) -- reaching the pad is what the
    forced-use guarantee actually rests on here, not the pad's own
    location relative to the pocket: once sealed, the pocket is a genuine,
    physically-enforced wall no augment/movement rule can bypass, so
    *any* cell inside it is unreachable until this specific pad fires,
    full stop.

    `committed` is every mandatory pad already placed earlier in this same
    chain -- when chaining (current_start sits inside an earlier pad's own
    sealed pocket), that earlier pocket's wall is *still closed* in
    ctx.grid, so a plain/real-move reachability walk from ctx.start can
    never reach current_start (or this new pad's own candidate location)
    at all. Reachability here is computed against a *planning* grid with
    every already-committed pad pre-opened instead -- exactly mirroring
    how doors.py's own chained mandatory doors are verified by assuming
    every earlier door's key was already collected (_reachable_before_a_new_door),
    not by requiring them to already be literally unlocked in ctx.grid.

    Verifies (rather than assumes) that reopening wall_segment alone
    reconnects the *entire* pocket back to the main region via plain
    bfs_reachable() -- true by construction (it's the exact tree-parent
    edge pendant_subtree_map() found), but checked directly rather than
    trusted, matching this project's existing verify-don't-assume pattern.

    Mutates ctx.grid/ctx.reserved/ctx.frontier/ctx.extra in place on
    success. Returns None if no candidate works out (graceful degradation).
    """
    order, subtree, _parent = pendant_subtree_map(ctx.grid, current_start)
    local_forbidden = nested_local_forbidden(ctx, current_start)
    forbidden = {current_start} | (local_forbidden if local_forbidden is not None else ctx.reserved)
    candidates = [c for c in order if c != current_start and c not in forbidden]
    if not candidates:
        return None

    in_range = [c for c in candidates if SHIFT_POCKET_MIN_SIZE <= len(subtree[c]) <= SHIFT_POCKET_MAX_SIZE]
    if in_range:
        pool = in_range
    else:
        total = len(order)
        big_enough = [
            c for c in candidates
            if SHIFT_POCKET_MIN_SIZE <= len(subtree[c]) <= max(total // 2, SHIFT_POCKET_MIN_SIZE)
        ]
        if not big_enough:
            return None
        smallest = min(len(subtree[c]) for c in big_enough)
        pool = [c for c in big_enough if len(subtree[c]) == smallest]

    teleport = lambda x, y: tmap.get((x, y))

    for _ in range(SHIFT_PLACEMENT_MAX_ATTEMPTS):
        if not pool:
            return None
        chosen = ctx.rng.choice(pool)
        pool = [c for c in pool if c != chosen]
        blob = subtree[chosen]

        crossings = boundary_crossings(ctx.grid, blob)
        if not crossings:
            continue  # shouldn't happen for a non-root pendant subtree, but be defensive
        wall_segment = ctx.rng.choice(list(crossings))
        sealed_grid = seal_pocket(ctx.grid, blob)

        # Planning grid: pre-open every already-committed mandatory pad's
        # wall (current_start, and this whole candidate blob, may sit
        # behind one of them -- see this function's docstring). Real
        # gameplay reachability, not the literal current ctx.grid state.
        planning_grid = _opened_for_planning(sealed_grid, committed)
        reachable = sequentially_reachable(planning_grid, ctx.start, doors, teleport=teleport)
        if not blob.isdisjoint(reachable):
            # An already-placed teleporter has an endpoint inside this
            # candidate blob -- seal_pocket() only re-walls *physical*
            # boundary crossings, but a teleporter's edge isn't physical
            # (slide_path()'s teleport hook fires regardless of walls), so
            # the pocket would already be reachable via that bridge, making
            # the pad a no-op decoy rather than a genuine gate. Try another
            # candidate instead of silently placing a pointless/bypassable one.
            continue
        # Uses `forbidden` (the narrow nested_local_forbidden() set when
        # nested, ctx.reserved otherwise), NOT ctx.reserved directly -- see
        # teleporters.py's identical fix/comment for why: when current_start
        # sits inside an already-sealed outer pocket, `reachable`/`blob` are
        # both subsets of that already-fully-reserved outer blob, so a raw
        # ctx.reserved check would reject every candidate and silently cap
        # chained mandatory pads at 1 regardless of level.
        pad_candidates = [
            c for c in reachable
            if c not in forbidden and c != current_start and is_stoppable_cell(planning_grid, *c)
        ]
        if not pad_candidates:
            continue
        pad_cell = ctx.rng.choice(pad_candidates)

        wx, wy = wall_segment
        opened_grid = [row[:] for row in sealed_grid]
        opened_grid[wy][wx] = 0
        if not blob <= bfs_reachable(opened_grid, chosen):
            continue  # verify the reopened crossing genuinely restores the whole pocket -- should always hold by construction

        frontier_candidates = [c for c in blob if c not in forbidden and is_stoppable_cell(opened_grid, *c)]
        if not frontier_candidates:
            continue

        ctx.grid = sealed_grid
        ctx.reserved |= blob | {pad_cell}
        # Overwrite, not union -- see teleporters.py's identical comment
        # (each subsequent mandatory placement nests inside the last, so
        # the newest gated blob is always the correct, tightest one).
        ctx.extra["mandatory_gated_cells"] = blob
        ctx.frontier = ctx.rng.choice(frontier_candidates)
        return PressurePad(pad=pad_cell, wall_segment=wall_segment, mandatory=True, color_index=color_index)

    return None


def _place_decorative_pads(
    ctx: AugmentContext,
    tmap: dict[tuple[int, int], tuple[int, int]],
    doors: list,
    mandatory_pads: list[PressurePad],
    count: int,
    start_index: int,
) -> list[PressurePad]:
    """
    Purely optional pockets: sealed the same way as a mandatory pad, but
    candidates whose subtree contains ctx.frontier are excluded up front
    (sealing one must never trap the established mandatory chain), and
    each candidate is verified to leave ctx.frontier reachable afterward.
    Mirrors doors.py's _place_decorative_doors() shape, including
    computing the candidate pool once before the placement loop rather
    than per-pad -- sealing a pendant subtree can't affect any *other*
    candidate's own subtree (pendant subtrees from one pendant_subtree_map()
    call are always nested-or-disjoint, never partially overlapping), so a
    stale candidate that turns out to already be swallowed by an earlier
    placement is simply rejected by the reachability check below rather
    than needing to be filtered out proactively.

    `mandatory_pads` (every mandatory pad placed earlier in the same
    apply() call) matters for the ctx.frontier-reachability check: if any
    mandatory pad exists, ctx.frontier now sits *behind a real wall*, so
    verifying it against the literal, still-sealed ctx.grid would always
    fail. Reachability here is checked against a planning grid with those
    mandatory pads pre-opened instead -- see _place_mandatory_pad()'s
    identical reasoning. The pad's own placeable *location*, by contrast,
    still has to come from the real (non-planning) reachable set, since a
    decorative pad has to be somewhere the player can actually walk to
    without having triggered anything yet.
    """
    if count <= 0:
        return []
    order, subtree, _parent = pendant_subtree_map(ctx.grid, ctx.start)
    candidates = [
        c for c in order
        if c != ctx.start and c not in ctx.reserved and ctx.frontier not in subtree[c]
        and SHIFT_POCKET_MIN_SIZE <= len(subtree[c]) <= SHIFT_POCKET_MAX_SIZE
    ]
    teleport = lambda x, y: tmap.get((x, y))

    pads: list[PressurePad] = []
    for i in range(count):
        placed = False
        for _ in range(SHIFT_PLACEMENT_MAX_ATTEMPTS):
            if not candidates:
                break
            chosen = ctx.rng.choice(candidates)
            candidates = [c for c in candidates if c != chosen]
            blob = subtree[chosen]

            crossings = boundary_crossings(ctx.grid, blob)
            if not crossings:
                continue
            wall_segment = ctx.rng.choice(list(crossings))
            sealed_grid = seal_pocket(ctx.grid, blob)

            # Planning grid (mandatory pads pre-opened) for the
            # frontier/disjointness checks -- ctx.frontier may currently
            # sit behind one of them, see this function's docstring.
            planning_grid = _opened_for_planning(sealed_grid, mandatory_pads)
            planning_reachable = sequentially_reachable(planning_grid, ctx.start, doors, teleport=teleport)
            if ctx.frontier not in planning_reachable:
                continue  # this pocket's sealing broke the established mandatory chain -- try another
            if not blob.isdisjoint(planning_reachable):
                # An already-placed teleporter bridges into this candidate
                # blob -- see _place_mandatory_pad()'s identical check. Less
                # critical here (nothing mandatory rests on it), but still a
                # pointless pad if triggering it changes nothing.
                continue

            # The pad's own location, unlike the checks above, must come
            # from the *real* (non-planning) reachable set -- the player
            # has to be able to actually walk to a decorative pad without
            # having triggered anything yet.
            reachable = sequentially_reachable(sealed_grid, ctx.start, doors, teleport=teleport)
            pad_candidates = [c for c in reachable if c not in ctx.reserved and is_stoppable_cell(sealed_grid, *c)]
            if not pad_candidates:
                continue
            pad_cell = ctx.rng.choice(pad_candidates)

            ctx.grid = sealed_grid
            ctx.reserved |= blob | {pad_cell}
            candidates = [c for c in candidates if c not in blob]
            pads.append(PressurePad(pad=pad_cell, wall_segment=wall_segment, mandatory=False, color_index=start_index + len(pads)))
            placed = True
            break
        if not placed:
            break  # graceful degradation -- fewer decorative pads than requested
    return pads
