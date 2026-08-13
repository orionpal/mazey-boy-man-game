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
that looked like a genuine cut vertex under plain grid adjacency.

**Mandatory door placement doesn't search for a pocket containing the
goal.** An earlier version did, and that was a real bug: playtesting found
mazes where TeleportersAugment had already relocated the goal behind its
own sealed, teleporter-only pocket, invisible to this module's plain-grid
pendant_subtree_map() search -- no mandatory door candidate could ever
contain that goal, so DoorsAugment silently placed 0 mandatory doors *every
time* Teleporters had a mandatory pair active, spending its whole pair
budget on decoratives instead. Doors was "active" per the player's build,
but the maze never actually required opening one -- the exact "Doors could
be skipped entirely" report this fixed. The fix (shared with the other
gating augments, see augments/__init__.py's `AugmentContext.mandatory_frontier`
and `run_pipeline()`'s docstring): mandatory doors nest onto the shared
cross-augment `ctx.mandatory_frontier` instead of hunting for the current
`ctx.goal`, and final goal placement is deferred to run_pipeline(), once,
after every active augment has had a turn.

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
from maze_game.maze import is_stoppable_cell
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
        current_start = ctx.mandatory_frontier
        for i in range(mandatory_count):
            result = _place_mandatory_door(ctx, current_start, tmap, color_index=i, committed=pairs)
            if result is None:
                break  # graceful degradation -- fewer mandatory doors than the formula asked for
            pair, frontier_cell = result
            pairs.append(pair)
            # Nest off (and advance the checkpoint to) a verified-stoppable
            # cell inside the door's own pocket -- not `pair.door` itself,
            # see _place_mandatory_door()'s docstring for why that used to
            # silently make every reachability check against it vacuous.
            current_start = frontier_cell

        if pairs:
            # Advance the shared cross-augment checkpoint rather than gating
            # whatever ctx.goal happens to be right now -- see
            # run_pipeline()'s docstring for why: an earlier augment
            # (teleporters) may already have moved the goal somewhere this
            # module's plain-grid pocket search can't see at all, which used
            # to silently degrade this loop to 0 mandatory doors every time.
            ctx.mandatory_frontier = current_start

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
) -> tuple[DoorKeyPair, tuple[int, int]] | None:
    """
    Pick a pendant subtree of `current_start`'s BFS tree whose size lands in
    [DOOR_FAR_SIDE_MIN_SIZE, DOOR_FAR_SIDE_MAX_SIZE] (falling back to the
    smallest such subtree if none lands exactly in range, same shape as
    teleporters' fallback). Physically re-walls the whole subtree's
    boundary except the crossing into its root (seal_pocket()) -- that
    root becomes the door, still grid-open but now the sole way in or out.

    Deliberately does *not* require the subtree to contain `ctx.goal`
    (unlike an earlier version of this function): `ctx.goal` isn't final
    mid-pipeline (see run_pipeline()'s docstring), and an earlier augment
    may already have moved it somewhere this plain-grid pendant-subtree
    search can't see at all (e.g. sealed behind a teleporter-only pocket) --
    that used to silently degrade every mandatory door to 0, exactly the
    "Doors could be skipped entirely" bug this module's tests now guard
    against. Any pendant subtree of `current_start` is, by construction,
    already gated by its own root once sealed -- same as teleporters'/
    multi-level's mandatory pockets, which never needed a "contains goal"
    check either, precisely because they own their own goal placement. This
    function's caller does the analogous thing: advances
    `ctx.mandatory_frontier` to the returned frontier cell once placed, and
    the actual final goal gets chosen once, after the whole pipeline runs.

    Verifies with the *full* sequentially_reachable() -- not just a
    pairwise "is `current_start` still reachable with this one door locked"
    check -- before committing: sealing this pocket's boundary can, in
    rare cases, sever the *only* remaining path to an earlier door's key
    (a braid() loop that used to route through what's now sealed-off
    territory), silently breaking that earlier door even though this
    candidate looks fine in isolation. Found via this module's own
    end-to-end test suite; a pairwise check alone missed it. Checking
    `current_start` (rather than `ctx.goal`) also transparently protects
    an *earlier augment's* mandatory chain when this is the first door
    placed off an inherited `ctx.mandatory_frontier` -- current_start IS
    that frontier in that case, so the same check does double duty.

    **Returns the door's own cell separately from the checkpoint used for
    verification and nesting.** `door_cell` itself is frequently a plain
    2-open-neighbour corridor cell once unlocked (it only had one open side
    -- the entrance -- forced by `seal_pocket()`, plus however many children
    its pendant subtree happens to have; a single-child subtree, the common
    case, leaves it at exactly 2) -- `player.slide()` only ever stops at a
    wall ahead or a junction (3+ open neighbours), so real movement can
    *never land exactly on it*, unlocked or not (see `maze.py`'s
    `is_stoppable_cell`/`farthest_reachable_cell` for the same rule
    elsewhere). Checking `door_cell` itself for membership in a
    `real_move_reachable()`/`sequentially_reachable()` result was therefore
    checking something that could be false 100% of the time regardless of
    whether the door was ever actually passable -- the exact bug that
    silently capped every level at 1 real mandatory door (the *first* one's
    check is vacuously true, since `current_start` there is just `ctx.start`,
    always trivially reachable) and starved every decorative door's own
    frontier check (which had no such vacuous first-door exemption) at a
    ~100% rate. Fixed by picking a genuinely stoppable cell from inside the
    now-sealed pocket (`subtree[door_cell]`, which always contains at least
    one -- a fully re-walled pendant subtree's own leaves are dead ends by
    construction, and a dead end is always stoppable) and using *that* as
    both the nesting root for a subsequent mandatory door and the
    checkpoint `ctx.mandatory_frontier` ends up holding. The door tile
    itself (`candidate.door`) is unaffected -- it's still exactly where the
    player unlocks and steps past; only the internal "did we get far enough"
    bookkeeping moved off of it.

    Mutates ctx.grid/ctx.reserved in place on success. Returns None if no
    candidate works out (graceful degradation -- the caller places fewer
    mandatory doors than the level formula asked for).

    Passes every already-committed door's cell as `pendant_subtree_map()`'s
    `blocked` set: a door's own cell deliberately stays grid-open (see this
    module's docstring), so an unblocked search rooted at a `current_start`
    already nested behind an earlier door in this same chain would silently
    walk right back out through it, discovering "local" territory that's
    actually that earlier door's own already-claimed cells -- which the
    `ctx.reserved - set(order)` subtraction just below would then treat as
    fair game again, letting a new door collide with (or literally reuse
    the exact cell of) one already placed. Found via this module's own
    end-to-end tests once goal placement became movement-aware enough to
    actually land inside the nested chain and expose it (see
    `augments/__init__.py::run_pipeline()`'s docstring).
    """
    blocked_doors = frozenset(pair.door for pair in committed)
    order, subtree, parent = pendant_subtree_map(ctx.grid, current_start, blocked=blocked_doors)
    # See teleporters.py::_place_mandatory_pair's identical line for why:
    # current_start's own local territory is necessarily already in
    # ctx.reserved (it's the pocket the previous chain step just sealed),
    # so it has to be subtracted back out here or nesting a second
    # mandatory gate inside it could never find a candidate.
    forbidden = (ctx.reserved - set(order)) | {current_start}
    candidates = [c for c in order if c not in forbidden]
    if not candidates:
        return None  # nothing off current_start via plain grid adjacency at all

    in_range = [c for c in candidates if DOOR_FAR_SIDE_MIN_SIZE <= len(subtree[c]) <= DOOR_FAR_SIDE_MAX_SIZE]
    if in_range:
        pool = in_range
    else:
        big_enough = [c for c in candidates if len(subtree[c]) >= DOOR_FAR_SIDE_MIN_SIZE]
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

        # A stoppable cell inside the sealed pocket -- see the docstring
        # above for why door_cell itself can't reliably serve as the
        # "did we get past this gate" checkpoint. Guaranteed non-empty: a
        # fully re-walled pendant subtree's leaves are dead ends (1 open
        # neighbour), always stoppable.
        #
        # `subtree[door_cell]` includes `door_cell` itself (pendant_subtree_map()
        # seeds every node's subtree with `{node}` before folding in its
        # children) -- and door_cell occasionally *does* satisfy
        # is_stoppable_cell() post-sealing (a 3-way junction where the
        # entrance and two interior branches meet, say), so without an
        # explicit `c != door_cell` guard here it could still get chosen as
        # frontier_cell despite the whole point of this filter being to
        # rule it out. Real incident, 2026-08-12: with a door cell as the
        # checkpoint, a *second* mandatory door nested off it (current_start
        # sits right on the door's own inside/outside boundary, which stays
        # grid-open on both sides) could end up sealing a pocket that
        # includes territory *outside* the first door entirely, landing its
        # own frontier back in the original unsealed maze -- silently
        # defeating the whole nesting guarantee two gates deep (caught by
        # test_every_combination_of_active_gating_augments_forces_every_gate,
        # doors+multi_level, seed 16 -- multi_level was a red herring, this
        # reproduces with doors alone).
        frontier_candidates = [
            c for c in subtree[door_cell] if c != door_cell and is_stoppable_cell(sealed_grid, *c)
        ]
        if not frontier_candidates:
            continue
        frontier_cell = ctx.rng.choice(frontier_candidates)

        candidate = DoorKeyPair(door=door_cell, key=key_cell, mandatory=True, color_index=color_index)
        final_reachable = sequentially_reachable(sealed_grid, ctx.start, committed + [candidate], teleport=teleport)
        if current_start not in final_reachable or frontier_cell not in final_reachable:
            # Sealing this pocket broke solvability somewhere -- either it
            # accidentally cut off an earlier door's key (current_start is
            # locked behind that earlier door, so it'd never become
            # reachable again), or -- when current_start is itself an
            # inherited ctx.mandatory_frontier from an earlier augment --
            # it severed that augment's own mandatory chain -- or the new
            # door's own pocket (frontier_cell) never actually opens up.
            # Try another.
            continue

        ctx.grid = sealed_grid
        ctx.reserved |= {door_cell, key_cell}
        return candidate, frontier_cell

    return None


def _place_decorative_doors(
    ctx: AugmentContext,
    tmap: dict[tuple[int, int], tuple[int, int]],
    count: int,
    start_index: int,
    committed: list[DoorKeyPair],
) -> list[DoorKeyPair]:
    """
    Purely optional gates: candidates whose subtree does *not* contain
    `ctx.mandatory_frontier` (so sealing one never blocks the established
    mandatory-gate chain -- possibly just extended by this augment's own
    mandatory loop above, possibly inherited from an earlier augment), each
    verified the same way _place_mandatory_door() does -- the full
    sequentially_reachable() outcome, with every already-committed
    mandatory door included, must still reach that frontier, and this new
    door's own pocket must genuinely be gated by it (checked via a
    far-side sample cell, since subtree-exclusion from the frontier alone
    doesn't rule out a braid()/teleporter bypass making it an inert,
    pointless always-open cell instead of a real gate). Checked against the
    frontier rather than `ctx.goal`, since the final goal isn't decided
    until every active augment has run (see run_pipeline()).
    """
    if count <= 0:
        return []
    order, subtree, parent = pendant_subtree_map(ctx.grid, ctx.start)
    candidates = [
        c for c in order
        if c not in ctx.reserved and ctx.mandatory_frontier not in subtree[c]
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
            if ctx.mandatory_frontier not in final_reachable:
                continue  # broke solvability of the established mandatory chain somewhere -- try another candidate

            ctx.grid = sealed_grid
            ctx.reserved |= {door_cell, key_cell}
            candidates = [c for c in candidates if c != key_cell]
            pairs.append(candidate)
            placed = True
            break
        if not placed:
            break  # graceful degradation -- fewer decorative doors than requested
    return pairs
