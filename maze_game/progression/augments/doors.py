"""
doors.py
--------
The second maze augment: doors & keys. A locked door blocks progress until
its matching key -- placed somewhere reachable *before* the door -- is
collected; collecting it unlocks that door permanently for the rest of the
maze. Structurally mirrors teleporters.py (generate a candidate, verify by
simulating real movement, retry, degrade gracefully -- see _movement.py's
real_move_reachable()/pendant_subtree_map()), but as a *gate* instead of a
*shortcut*.

A locked door's own cell is a behavioral gate, not a real wall (see
player.slide_path()'s door_locked hook): it stays grid-open the whole time,
so every BFS-based planning helper (shortest_path, farthest_reachable_cell,
bfs_reachable, ...) treats it as ordinarily passable and never needs to
know doors exist at all. This sidesteps the class of crash a fully-real-wall
approach would risk (shortest_path() finding no path to a target that's
genuinely unreachable at generation time, before any key has been
collected -- the same bug class recently fixed for Boss.advance()).

That alone isn't sufficient for correctness, though: a single behaviorally-
gated cell is *not* a reliable cut vertex in a braided maze (braid() adds
loop-forming extra edges by design, and empirically one very often bypasses
a lone gated cell -- discovered by this module's own test suite failing at
a 100% rate before this fix). So placement physically re-walls the *entire*
boundary of the chosen pocket (seal_pocket(), the exact technique
teleporters.py uses for its sealed pockets) except for the one crossing
into the door cell itself, which is deliberately left open. That crossing
is the only way in or out once sealed, so behaviorally gating just that one
(still grid-open) cell now genuinely gates the whole pocket -- combining a
real wall's immunity to loop bypasses with a behavioral gate's invisibility
to BFS-based planning. The one accepted consequence: any *future* BFS-based
planning call added elsewhere must remember a door cell itself is invisible
to it by design, same as this module's own solvability checks must walk the
real movement graph (real_move_reachable()) rather than plain grid adjacency.

Must run *after* TeleportersAugment in augments/__init__.py's ALL_AUGMENTS
registry -- a door candidate is verified against the maze's already-
finalized teleporter map, so a teleporter can never silently bypass a door
that looked like a genuine cut vertex under plain grid adjacency. If
TeleportersAugment has already relocated the goal behind a sealed,
teleporter-only pocket, that pocket is invisible to this module's plain-grid
pendant_subtree_map() search (by design -- it's really sealed), so no
mandatory door candidate can ever contain the goal in its subtree in that
case; DoorsAugment then gracefully places 0 mandatory doors and spends its
whole pair budget on decorative ones instead, exactly like running out of
placement attempts does.

Level scaling: level 1 places a couple of pairs with only one mandatory;
higher levels add more pairs and make more of them mandatory (see DOOR_*
constants), each successive mandatory door nested one region deeper than
the last.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from maze_game.constants import (
    DOOR_PAIR_COUNT_BASE, DOOR_PAIR_COUNT_STEP, DOOR_PAIR_COUNT_MAX,
    DOOR_MANDATORY_COUNT_BASE, DOOR_MANDATORY_COUNT_STEP,
    DOOR_FAR_SIDE_MIN_SIZE, DOOR_FAR_SIDE_MAX_SIZE, DOOR_PLACEMENT_MAX_ATTEMPTS,
    C_DOOR_KEY_PAIRS,
)
from maze_game.progression.augments import Augment, AugmentContext
from maze_game.progression.augments._movement import pendant_subtree_map, real_move_reachable, seal_pocket
from maze_game.progression.entities import MazeEntity

if TYPE_CHECKING:
    from maze_game.progression.run import LabyrinthRun


@dataclass(frozen=True)
class DoorKeyPair:
    door: tuple[int, int]
    key: tuple[int, int]
    mandatory: bool
    color_index: int


class Key(MazeEntity):
    """A one-time pickup that unlocks its paired door for the rest of the maze."""

    def __init__(self, pos: tuple[int, int], door_cell: tuple[int, int]) -> None:
        super().__init__(pos)
        self.door_cell = door_cell

    def on_contact(self, run: "LabyrinthRun") -> None:
        run._locked_doors.discard(self.door_cell)
        colour = C_DOOR_KEY_PAIRS[0]
        for pair in run.doors:
            if pair.key == self.pos:
                colour = C_DOOR_KEY_PAIRS[pair.color_index % len(C_DOOR_KEY_PAIRS)]
                break
        run.add_popup(self.pos, "key!", colour)
        run.events.append("key")


class DoorsAugment(Augment):
    id = "doors"
    name = "Doors & Keys"
    description = (
        "A locked door blocks the way until you find its key. "
        "Higher levels add more door/key pairs, and more of them mandatory to reach the goal."
    )

    def apply(self, ctx: AugmentContext) -> None:
        pair_count = min(
            DOOR_PAIR_COUNT_BASE + DOOR_PAIR_COUNT_STEP * (ctx.level - 1),
            DOOR_PAIR_COUNT_MAX,
        )
        mandatory_count = min(
            DOOR_MANDATORY_COUNT_BASE + DOOR_MANDATORY_COUNT_STEP * (ctx.level - 1),
            pair_count,
        )
        tmap = _existing_teleport_map(ctx)

        pairs: list[DoorKeyPair] = []
        current_start = ctx.start
        for i in range(mandatory_count):
            pair = _place_mandatory_door(ctx, current_start, tmap, color_index=i, committed=pairs)
            if pair is None:
                break  # graceful degradation -- fewer mandatory doors than the formula asked for
            pairs.append(pair)
            current_start = pair.door  # next search rooted deeper, same nesting technique as teleporters

        decorative_count = pair_count - len(pairs)
        pairs.extend(_place_decorative_doors(ctx, tmap, decorative_count, start_index=len(pairs), committed=pairs))

        ctx.extra["doors"] = pairs


def _existing_teleport_map(ctx: AugmentContext) -> dict[tuple[int, int], tuple[int, int]]:
    """The already-finalized teleporter map (if TeleportersAugment ran first), for the real-move reachability checks below."""
    tmap: dict[tuple[int, int], tuple[int, int]] = {}
    for pair in ctx.extra.get("teleporters", []):
        tmap[pair.a] = pair.b
        tmap[pair.b] = pair.a
    return tmap


def _door_entrance_midpoint(door_cell: tuple[int, int], parent_cell: tuple[int, int]) -> tuple[int, int]:
    """The wall-segment coordinate between a pendant-subtree root and its tree parent -- the one crossing seal_pocket() should leave open."""
    return (door_cell[0] + parent_cell[0]) // 2, (door_cell[1] + parent_cell[1]) // 2


def sequentially_reachable(
    grid: list[list[int]],
    start: tuple[int, int],
    doors: list[DoorKeyPair],
    teleport=None,
) -> set[tuple[int, int]]:
    """
    The region reachable once every key that ever becomes reachable has
    been collected, in any valid order -- collecting one key can reveal
    the path to another, so a single reachable_locked() snapshot with
    everything locked isn't the real answer to "what can the player
    actually get to." This is the ground-truth solvability check both
    placement functions below verify every candidate against, and
    (imported directly, not re-derived) what tests/progression/augments/
    test_doors.py's own end-to-end tests use too.
    """
    locked = {pair.door for pair in doors}
    key_owner = {pair.key: pair.door for pair in doors}
    while True:
        reachable = real_move_reachable(grid, start, teleport=teleport, door_locked=lambda x, y: (x, y) in locked)
        newly_unlocked = {key_owner[k] for k in key_owner if k in reachable and key_owner[k] in locked}
        if not newly_unlocked:
            return reachable
        locked -= newly_unlocked


def _reachable_before_a_new_door(
    grid: list[list[int]],
    start: tuple[int, int],
    already_committed: list[DoorKeyPair],
    new_door_cell: tuple[int, int],
    teleport=None,
) -> set[tuple[int, int]]:
    """
    sequentially_reachable(), but also holding `new_door_cell` locked for
    the entire simulation -- used while a new door is still being placed,
    before it has a key of its own to pass to sequentially_reachable()
    directly. A dummy self-keyed pair (key == door) guarantees it's never
    "collected": a locked cell can never appear in `reachable`, so it can
    never satisfy its own unlock condition.
    """
    probe = already_committed + [DoorKeyPair(door=new_door_cell, key=new_door_cell, mandatory=True, color_index=-1)]
    return sequentially_reachable(grid, start, probe, teleport=teleport)


def _place_mandatory_door(
    ctx: AugmentContext,
    current_start: tuple[int, int],
    tmap: dict[tuple[int, int], tuple[int, int]],
    color_index: int,
    committed: list[DoorKeyPair],
) -> DoorKeyPair | None:
    """
    Pick a pendant subtree of `current_start`'s BFS tree that contains
    ctx.goal (guaranteeing mandatory-ness structurally: sealing it off
    really does gate the route to the goal) and whose size lands in
    [DOOR_FAR_SIDE_MIN_SIZE, DOOR_FAR_SIDE_MAX_SIZE] (falling back to the
    smallest such subtree if none lands exactly in range, same shape as
    teleporters' fallback). Physically re-walls the whole subtree's
    boundary except the crossing into its root (seal_pocket()) -- that
    root becomes the door, still grid-open but now the sole way in or out.

    Verifies with the *full* sequentially_reachable() -- not just a
    pairwise "is the goal still reachable with this one door locked"
    check -- before committing: sealing this pocket's boundary can, in
    rare cases, sever the *only* remaining path to an earlier door's key
    (a braid() loop that used to route through what's now sealed-off
    territory), silently breaking that earlier door even though this
    candidate looks fine in isolation. Found via this module's own
    end-to-end test suite; a pairwise check alone missed it.

    Mutates ctx.grid/ctx.reserved in place on success. Returns None if no
    candidate works out (graceful degradation -- the caller places fewer
    mandatory doors than the level formula asked for).
    """
    order, subtree, parent = pendant_subtree_map(ctx.grid, current_start)
    forbidden = ctx.reserved | {current_start}
    gates_the_goal = [c for c in order if c not in forbidden and ctx.goal in subtree[c]]
    if not gates_the_goal:
        return None  # the goal isn't reachable from here via plain grid adjacency at all (e.g. sealed behind a teleporter pocket)

    in_range = [c for c in gates_the_goal if DOOR_FAR_SIDE_MIN_SIZE <= len(subtree[c]) <= DOOR_FAR_SIDE_MAX_SIZE]
    if in_range:
        pool = in_range
    else:
        big_enough = [c for c in gates_the_goal if len(subtree[c]) >= DOOR_FAR_SIDE_MIN_SIZE]
        if not big_enough:
            return None
        smallest = min(len(subtree[c]) for c in big_enough)
        pool = [c for c in big_enough if len(subtree[c]) == smallest]

    teleport = lambda x, y: tmap.get((x, y))

    for _ in range(DOOR_PLACEMENT_MAX_ATTEMPTS):
        if not pool:
            return None
        door_cell = ctx.rng.choice(pool)
        pool = [c for c in pool if c != door_cell]

        entrance = _door_entrance_midpoint(door_cell, parent[door_cell])
        sealed_grid = seal_pocket(ctx.grid, subtree[door_cell], keep_open=frozenset({entrance}))

        near_side = _reachable_before_a_new_door(sealed_grid, ctx.start, committed, door_cell, teleport=teleport)
        key_candidates = [c for c in near_side if c not in ctx.reserved and c != door_cell]
        if not key_candidates:
            continue
        key_cell = ctx.rng.choice(key_candidates)

        candidate = DoorKeyPair(door=door_cell, key=key_cell, mandatory=True, color_index=color_index)
        final_reachable = sequentially_reachable(sealed_grid, ctx.start, committed + [candidate], teleport=teleport)
        if ctx.goal not in final_reachable:
            # Sealing this pocket broke solvability somewhere -- either
            # this candidate isn't a genuine gate (a loop bypasses it), or
            # it accidentally cut off an earlier door's key. Try another.
            continue

        ctx.grid = sealed_grid
        ctx.reserved |= {door_cell, key_cell}
        return candidate

    return None


def _place_decorative_doors(
    ctx: AugmentContext,
    tmap: dict[tuple[int, int], tuple[int, int]],
    count: int,
    start_index: int,
    committed: list[DoorKeyPair],
) -> list[DoorKeyPair]:
    """
    Purely optional gates: candidates whose subtree does *not* contain the
    goal (so sealing one never blocks the route to the goal itself), each
    verified the same way _place_mandatory_door() does -- the full
    sequentially_reachable() outcome, with every already-committed
    mandatory door included, must still reach the goal, and this new
    door's own pocket must genuinely be gated by it (checked via a
    far-side sample cell, since subtree-exclusion from the goal alone
    doesn't rule out a braid()/teleporter bypass making it an inert,
    pointless always-open cell instead of a real gate).
    """
    if count <= 0:
        return []
    order, subtree, parent = pendant_subtree_map(ctx.grid, ctx.start)
    candidates = [
        c for c in order
        if c not in ctx.reserved and ctx.goal not in subtree[c]
        and DOOR_FAR_SIDE_MIN_SIZE <= len(subtree[c]) <= DOOR_FAR_SIDE_MAX_SIZE
    ]
    teleport = lambda x, y: tmap.get((x, y))

    pairs: list[DoorKeyPair] = []
    for i in range(count):
        placed = False
        for _ in range(DOOR_PLACEMENT_MAX_ATTEMPTS):
            if not candidates:
                break
            door_cell = ctx.rng.choice(candidates)
            candidates = [c for c in candidates if c != door_cell]

            entrance = _door_entrance_midpoint(door_cell, parent[door_cell])
            sealed_grid = seal_pocket(ctx.grid, subtree[door_cell], keep_open=frozenset({entrance}))

            near_side = _reachable_before_a_new_door(sealed_grid, ctx.start, committed + pairs, door_cell, teleport=teleport)
            far_side_sample = next(iter(subtree[door_cell] - {door_cell}), None)
            if far_side_sample is not None and far_side_sample in near_side:
                continue  # a loop still bypasses the seal -- not a genuine gate, wouldn't actually gate anything

            key_candidates = [c for c in near_side if c not in ctx.reserved and c != door_cell]
            if not key_candidates:
                continue
            key_cell = ctx.rng.choice(key_candidates)

            candidate = DoorKeyPair(door=door_cell, key=key_cell, mandatory=False, color_index=start_index + i)
            final_reachable = sequentially_reachable(sealed_grid, ctx.start, committed + pairs + [candidate], teleport=teleport)
            if ctx.goal not in final_reachable:
                continue  # broke solvability somewhere -- try another candidate

            ctx.grid = sealed_grid
            ctx.reserved |= {door_cell, key_cell}
            candidates = [c for c in candidates if c != key_cell]
            pairs.append(candidate)
            placed = True
            break
        if not placed:
            break  # graceful degradation -- fewer decorative doors than requested
    return pairs
