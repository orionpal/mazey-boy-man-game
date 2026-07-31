"""
teleporters.py
---------------
The first maze augment: teleporting squares. Guarantees the goal is
unreachable from the start via ordinary grid adjacency alone -- it seals
off a "pocket" of passage cells behind a re-walled boundary, verified with
bfs_reachable() (reject-and-retry on failure), so the only way in or out of
the pocket is the teleporter pair linking its entrance (in the main region)
to its exit (inside the pocket). Chained for multiple mandatory pairs
(nesting falls out for free: once a pocket is sealed, it's its own
isolated reachable component, so the next mandatory pair's search
automatically confines itself there), then topped up with purely
decorative pairs (optional shortcuts within the still-reachable main
region) up to the level's total pair count.

This is the concrete first application of the "generate, then
BFS-connectivity-check, retry/patch on failure" pattern
docs/maze-generation.md anticipated would eventually be needed for
topology-changing tiles like teleporters.

Level scaling: level 1 places a handful of pairs with only one mandatory;
higher levels add more pairs and make more of them mandatory (see
TELEPORT_* constants), each successive mandatory pair nested one pocket
deeper than the last.
"""

from __future__ import annotations

from dataclasses import dataclass

from maze_game.constants import (
    TELEPORT_PAIR_COUNT_BASE, TELEPORT_PAIR_COUNT_STEP, TELEPORT_PAIR_COUNT_MAX,
    TELEPORT_MANDATORY_COUNT_BASE, TELEPORT_MANDATORY_COUNT_STEP,
    TELEPORT_POCKET_MIN_SIZE, TELEPORT_POCKET_MAX_SIZE,
    TELEPORT_PLACEMENT_MAX_ATTEMPTS,
)
from maze_game.maze import bfs_reachable, is_stoppable_cell, farthest_reachable_cell
from maze_game.progression.augments import Augment, AugmentContext
from maze_game.progression.augments._movement import pendant_subtree_map, real_move_reachable, seal_pocket


@dataclass(frozen=True)
class TeleporterPair:
    a: tuple[int, int]
    b: tuple[int, int]
    mandatory: bool
    color_index: int


class TeleportersAugment(Augment):
    id = "teleporters"
    name = "Teleporting Squares"
    description = (
        "Step onto a pad to warp to its linked partner, and vice versa. "
        "Higher levels add more pairs, and more of them mandatory to reach the goal."
    )

    def apply(self, ctx: AugmentContext) -> None:
        pair_count = min(
            TELEPORT_PAIR_COUNT_BASE + TELEPORT_PAIR_COUNT_STEP * (ctx.level - 1),
            TELEPORT_PAIR_COUNT_MAX,
        )
        mandatory_count = min(
            TELEPORT_MANDATORY_COUNT_BASE + TELEPORT_MANDATORY_COUNT_STEP * (ctx.level - 1),
            pair_count,
        )

        pairs: list[TeleporterPair] = []
        current_start = ctx.start
        for i in range(mandatory_count):
            pair = _place_mandatory_pair(ctx, current_start, color_index=i, committed=pairs)
            if pair is None:
                break  # graceful degradation -- fewer mandatory pairs than the formula asked for
            pairs.append(pair)
            current_start = pair.b

        if pairs:
            ctx.goal = farthest_reachable_cell(ctx.grid, current_start)

        decorative_count = pair_count - len(pairs)
        pairs.extend(_place_decorative_pairs(ctx, decorative_count, start_index=len(pairs), committed=pairs))

        ctx.extra["teleporters"] = pairs


def _teleport_map(pairs: list[TeleporterPair]) -> dict[tuple[int, int], tuple[int, int]]:
    tmap: dict[tuple[int, int], tuple[int, int]] = {}
    for pair in pairs:
        tmap[pair.a] = pair.b
        tmap[pair.b] = pair.a
    return tmap


def _place_mandatory_pair(
    ctx: AugmentContext, current_start: tuple[int, int], color_index: int, committed: list[TeleporterPair],
) -> TeleporterPair | None:
    """
    Pick a pendant subtree of `current_start`'s BFS tree whose size lands in
    [TELEPORT_POCKET_MIN_SIZE, TELEPORT_POCKET_MAX_SIZE] (falling back to
    the smallest subtree at least that big, capped well below "most of the
    reachable region", if none lands exactly in range), seal it off, and
    return a TeleporterPair linking a stoppable entrance (main region) to a
    stoppable exit (pocket interior).

    Before committing, verifies with `real_move_reachable` (using
    `committed`'s teleporters plus this tentative one) that the exit is
    actually reachable from the *true* start via real moves -- the
    entrance cell forces an unconditional redirect the instant it's
    entered, so if it happens to sit on a junction load-bearing for some
    other part of the maze, plain grid-adjacency reachability wouldn't
    catch that it just broke solvability elsewhere. Retries with a
    different pocket/entrance/exit combination if the check fails.

    Mutates ctx.grid/ctx.reserved in place on success. Returns None if no
    candidate works out (graceful degradation -- the caller places fewer
    mandatory pairs than the level formula asked for).
    """
    order, subtree, _parent = pendant_subtree_map(ctx.grid, current_start)
    forbidden = ctx.reserved | {current_start}
    candidates = [c for c in order if c != current_start and c not in forbidden]
    if not candidates:
        return None

    in_range = [c for c in candidates if TELEPORT_POCKET_MIN_SIZE <= len(subtree[c]) <= TELEPORT_POCKET_MAX_SIZE]
    if in_range:
        pool = in_range
    else:
        total = len(order)
        big_enough = [
            c for c in candidates
            if len(subtree[c]) >= TELEPORT_POCKET_MIN_SIZE and len(subtree[c]) <= max(total // 2, TELEPORT_POCKET_MIN_SIZE)
        ]
        if not big_enough:
            return None
        smallest = min(len(subtree[c]) for c in big_enough)
        pool = [c for c in big_enough if len(subtree[c]) == smallest]

    base_tmap = _teleport_map(committed)

    for _ in range(TELEPORT_PLACEMENT_MAX_ATTEMPTS):
        if not pool:
            return None
        chosen = ctx.rng.choice(pool)
        pool = [c for c in pool if c != chosen]  # don't retry the exact same pocket
        blob = subtree[chosen]

        sealed_grid = seal_pocket(ctx.grid, blob)
        after = bfs_reachable(sealed_grid, current_start)
        pocket_region = bfs_reachable(sealed_grid, chosen)

        entrance_candidates = [
            c for c in after if c not in ctx.reserved and is_stoppable_cell(sealed_grid, *c)
        ]
        exit_candidates = [
            c for c in pocket_region if c not in ctx.reserved and is_stoppable_cell(sealed_grid, *c)
        ]
        if not entrance_candidates or not exit_candidates:
            continue

        entrance = ctx.rng.choice(entrance_candidates)
        exit_cell = ctx.rng.choice(exit_candidates)
        tentative_tmap = dict(base_tmap)
        tentative_tmap[entrance] = exit_cell
        tentative_tmap[exit_cell] = entrance

        if exit_cell not in real_move_reachable(sealed_grid, ctx.start, teleport=lambda x, y: tentative_tmap.get((x, y))):
            continue  # this entrance forces a redirect that breaks solvability elsewhere -- try a different pocket

        ctx.grid = sealed_grid
        ctx.reserved |= blob | {entrance, exit_cell}
        return TeleporterPair(a=entrance, b=exit_cell, mandatory=True, color_index=color_index)

    return None


def _place_decorative_pairs(
    ctx: AugmentContext, count: int, start_index: int, committed: list[TeleporterPair],
) -> list[TeleporterPair]:
    """
    Purely optional shortcuts: both endpoints stoppable, non-reserved cells
    within the still-reachable main region. Each candidate pair is verified
    with `real_move_reachable` before committing -- a decorative pad is
    just as capable of forcing an unwanted redirect through a load-bearing
    junction as a mandatory entrance is, and since decoratives are supposed
    to be purely optional, one that breaks the route to the goal is
    rejected outright rather than accepted with a worse maze.
    """
    if count <= 0:
        return []
    main_region = bfs_reachable(ctx.grid, ctx.start)
    candidates = [c for c in main_region if c not in ctx.reserved and is_stoppable_cell(ctx.grid, *c)]

    base_tmap = _teleport_map(committed)
    pairs: list[TeleporterPair] = []
    for i in range(count):
        placed = False
        for _ in range(TELEPORT_PLACEMENT_MAX_ATTEMPTS):
            if len(candidates) < 2:
                break
            a = ctx.rng.choice(candidates)
            remaining = [c for c in candidates if c != a]
            b = ctx.rng.choice(remaining)

            tentative_tmap = dict(base_tmap)
            tentative_tmap[a] = b
            tentative_tmap[b] = a

            if ctx.goal not in real_move_reachable(ctx.grid, ctx.start, teleport=lambda x, y: tentative_tmap.get((x, y))):
                continue  # this pair would cut off the route to the goal -- try a different pair

            candidates = [c for c in candidates if c not in (a, b)]
            ctx.reserved.add(a)
            ctx.reserved.add(b)
            base_tmap[a] = b
            base_tmap[b] = a
            pairs.append(TeleporterPair(a=a, b=b, mandatory=False, color_index=start_index + i))
            placed = True
            break
        if not placed:
            break  # graceful degradation -- fewer decorative pairs than requested
    return pairs
