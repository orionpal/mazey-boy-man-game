"""
_movement.py
------------
Shared graph-analysis helpers for augments that need to reason about real
player movement, not just plain grid adjacency -- promoted out of
teleporters.py (the first augment to need them) so a second augment (doors,
see doors.py) can reuse them instead of re-deriving the same subtleties.
Leading underscore: internal to augments/, not part of the public
Augment/AugmentContext API other code imports.
"""

from __future__ import annotations

from collections import deque

from maze_game.maze import is_stoppable_cell
from maze_game.player import slide_path

_PASSAGE_STEPS = ((0, -2), (0, 2), (-2, 0), (2, 0))
_DIRECTIONS = ((0, -1), (0, 1), (-1, 0), (1, 0))


def _passage_neighbors(grid: list[list[int]], cx: int, cy: int) -> list[tuple[int, int]]:
    """Odd,odd passage-cell neighbours reachable through an open wall-segment midpoint."""
    cols, rows = len(grid[0]), len(grid)
    neighbours = []
    for dx, dy in _PASSAGE_STEPS:
        nx, ny = cx + dx, cy + dy
        wx, wy = cx + dx // 2, cy + dy // 2
        if 0 <= nx < cols and 0 <= ny < rows and grid[wy][wx] == 0:
            neighbours.append((nx, ny))
    return neighbours


def pendant_subtree_map(grid, root, blocked: frozenset = frozenset()):
    """
    BFS spanning tree of the passage-cell graph reachable from `root`.
    Returns `(order, subtree, parent)`: `order` is the BFS visit order
    (every node's parent appears before it), `subtree[c]` is `c`'s full
    descendant closure (itself plus everything whose only tree-path back
    to `root` passes through it), `parent[c]` is `c`'s tree parent (`None`
    for `root`).

    This is the key correctness tool for pocket/gate placement: isolating
    `subtree[c]` in its entirety -- not some arbitrary same-size connected
    blob -- is guaranteed not to disconnect anything *outside* it, since by
    definition every cell outside `subtree[c]` still has its own tree-path
    to `root` that never touches `c`. A maze is close to a spanning tree
    (only sparse extra edges from `braid()`), so an arbitrary connected
    blob is usually a *bridge* for a large, unrelated part of the maze --
    picking a pendant subtree instead sidesteps that entirely.

    Note this only makes `subtree[c]` a *candidate* isolable region -- a
    `braid()` loop (or another augment's special edge, e.g. a teleporter)
    can still connect deep inside it back to the main region via some other
    crossing than the `parent[c]`-`c` tree edge. Actually isolating it
    requires re-walling every boundary crossing (see seal_pocket() below),
    not just blocking `c` itself; see doors.py for the concrete lesson this
    was learned from.

    `blocked`: cells the BFS must never step past, as if they were an
    unbroken wall. A locked door's own cell is deliberately left
    grid-*open* (see doors.py's "own cell stays grid-open" design), so
    plain adjacency alone can't tell it apart from ordinary floor -- which
    matters here specifically because a *second* gating augment (or this
    same one, placing a further-nested mandatory door) may root its own
    `pendant_subtree_map()` call at a `current_start` sitting behind an
    already-placed door. Without `blocked`, that call's `order` silently
    leaks back out through the door's still-open cell into territory well
    outside the caller's actual local pocket -- including cells an earlier
    placement already reserved (that door's own cell, its key, ...). A
    caller that then subtracts its *own* local territory back out of
    `ctx.reserved` (the standard nesting trick every placement function
    here uses -- see e.g. doors.py's `_place_mandatory_door`) ends up
    treating those leaked-in, already-claimed cells as fair game again,
    letting a brand new gate collide with (or literally reuse the exact
    cell of) one already placed. Pass every already-committed door's cell
    here to keep a nested search confined to genuinely new territory.
    """
    parent: dict[tuple[int, int], tuple[int, int] | None] = {root: None}
    order = [root]
    queue: deque[tuple[int, int]] = deque([root])
    while queue:
        cx, cy = queue.popleft()
        for n in _passage_neighbors(grid, cx, cy):
            if n not in parent and n not in blocked:
                parent[n] = (cx, cy)
                order.append(n)
                queue.append(n)

    children: dict[tuple[int, int], list[tuple[int, int]]] = {c: [] for c in order}
    for c, p in parent.items():
        if p is not None:
            children[p].append(c)

    subtree: dict[tuple[int, int], set[tuple[int, int]]] = {}
    for node in reversed(order):  # children always appear after their parent in BFS order
        s = {node}
        for child in children[node]:
            s |= subtree[child]
        subtree[node] = s

    return order, subtree, parent


def seal_pocket(grid, blob, keep_open: frozenset = frozenset()):
    """
    Re-wall every open wall-segment crossing the blob's boundary, except
    any wall-midpoint coordinate listed in `keep_open` (e.g. the one
    crossing a door should stay grid-open through). Returns a new grid;
    does not mutate the input.
    """
    sealed = [row[:] for row in grid]
    cols, rows = len(grid[0]), len(grid)
    for cx, cy in blob:
        for dx, dy in _PASSAGE_STEPS:
            nx, ny = cx + dx, cy + dy
            wx, wy = cx + dx // 2, cy + dy // 2
            if (
                0 <= nx < cols and 0 <= ny < rows
                and (nx, ny) not in blob and sealed[wy][wx] == 0
                and (wx, wy) not in keep_open
            ):
                sealed[wy][wx] = 1
    return sealed


def real_move_reachable(grid, start, *, teleport=None, door_locked=None):
    """
    BFS over the *real* movement-state graph: from each position, the only
    next positions are wherever a real player.slide_path() call (with
    whatever augment hooks are wired in, exactly as LabyrinthRun.move()
    does) lands in each of the 4 directions. This is the ground truth for
    "can the player actually get there" -- plain grid-adjacency
    reachability treats an augment's special edge (a teleporter link, a
    locked door) as separate from ordinary movement, but in real play it's
    never separate: a teleporter fires unconditionally the instant its cell
    is entered, overriding whatever direction the player intended, and a
    locked door blocks a cell that looks perfectly open to plain grid
    adjacency. A pad or gate placed on what would otherwise be a
    load-bearing junction can look connected to a naive check and still
    make the maze unsolvable -- this walks the same state graph
    slide_path()/move() actually produces, so it can't be fooled by that.
    """
    seen = {start}
    frontier = [start]
    while frontier:
        pos = frontier.pop()
        for direction in _DIRECTIONS:
            moved = slide_path(grid, pos, direction, teleport=teleport, door_locked=door_locked)
            if not moved:
                continue
            new_pos = moved[-1]
            if new_pos not in seen:
                seen.add(new_pos)
                frontier.append(new_pos)
    return seen


def real_move_farthest_cell(grid, start, *, teleport=None, door_locked=None):
    """
    Like `maze.farthest_reachable_cell()`, but BFS-walks the real
    `player.slide_path()` movement-state graph (same technique as
    `real_move_reachable()` above) instead of plain grid adjacency, so a
    caller can confine "farthest cell" to what's *actually* reachable under
    a given `teleport`/`door_locked` model rather than what's merely
    grid-connected.

    This is what `run_pipeline()` uses to place the final goal once every
    gating augment has run: plain `farthest_reachable_cell()` from
    `ctx.mandatory_frontier` walks ordinary grid adjacency, which still
    treats a locked door's cell as passable (`door_locked` is a
    `slide_path()`-only hook -- see doors.py's "own cell stays grid-open"
    design) and a teleporter/stairs link as just another pad sitting on the
    grid rather than the *only* way across a fully-sealed pocket boundary.
    Left unrestricted, that plain-grid walk can step back out of the
    pocket a gating augment just nested the frontier inside of and land the
    goal somewhere already reachable from `start` without ever passing the
    gate -- reintroducing the exact "Doors could be skipped" bug this
    module's cross-augment fix was for, just moved one step later in the
    pipeline. Passing `door_locked` covering every placed door (so the BFS
    can never grid-walk back out through one) and no `teleport` map at all
    (so it can never hop back out through a teleporter/stairs pad either,
    since every gating pocket's boundary is otherwise fully re-walled --
    see teleporters.py/multi_level.py's `seal_pocket()` calls) confines the
    search to exactly the territory that's only reachable *after* passing
    whatever gate(s) got the caller to `start` (here, `ctx.mandatory_frontier`)
    in the first place -- guaranteeing the chosen goal keeps that property
    too.

    **Candidate cells still need `is_stoppable_cell()`'s plain-grid-topology
    filter, same as `farthest_reachable_cell()` -- `door_locked` can itself
    manufacture a *fake* stopping point.** A door's own cell counts as a
    real neighbour for open-neighbour-count purposes but is otherwise a
    perfectly ordinary 2-neighbour corridor cell one step before it; with
    that door `door_locked`, `slide_path()` correctly stops one cell short
    of it -- but only because *this search* is treating the door as
    permanently locked. In real play the door unlocks the moment its key is
    collected, at which point that same corridor cell stops being a valid
    landing spot at all (the slide continues straight through it, into and
    past the now-open door) -- so picking it as the goal produces a cell
    that's provably unreachable once the very door gating it opens, the
    same failure shape `maze.farthest_reachable_cell()`'s docstring
    describes for plain 2-neighbour cells generally. Every cell this BFS
    lands on is a valid *stopping point under this search's own locked
    model*, but only ones that are also genuinely stoppable independent of
    any lock (`is_stoppable_cell()`, i.e. a real dead end or junction) are
    safe to return -- fake ones still get traversed *through* (so BFS
    distances past them stay correct), just never chosen as the answer.
    """
    dist = {start: 0}
    queue: deque[tuple[int, int]] = deque([start])
    farthest = start
    while queue:
        pos = queue.popleft()
        for direction in _DIRECTIONS:
            moved = slide_path(grid, pos, direction, teleport=teleport, door_locked=door_locked)
            if not moved:
                continue
            new_pos = moved[-1]
            if new_pos not in dist:
                dist[new_pos] = dist[pos] + 1
                queue.append(new_pos)
                if dist[new_pos] > dist[farthest] and is_stoppable_cell(grid, *new_pos):
                    farthest = new_pos
    return farthest
