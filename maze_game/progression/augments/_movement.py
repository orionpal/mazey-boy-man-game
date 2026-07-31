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


def pendant_subtree_map(grid, root):
    """
    BFS spanning tree of the passage-cell graph reachable from `root`.
    Returns `(order, subtree)`: `order` is the BFS visit order (every
    node's parent appears before it), `subtree[c]` is `c`'s full descendant
    closure (itself plus everything whose only tree-path back to `root`
    passes through it).

    This is the key correctness tool for pocket/gate placement: isolating
    `subtree[c]` in its entirety -- not some arbitrary same-size connected
    blob -- is guaranteed not to disconnect anything *outside* it, since by
    definition every cell outside `subtree[c]` still has its own tree-path
    to `root` that never touches `c`. A maze is close to a spanning tree
    (only sparse extra edges from `braid()`), so an arbitrary connected
    blob is usually a *bridge* for a large, unrelated part of the maze --
    picking a pendant subtree instead sidesteps that entirely.
    """
    parent: dict[tuple[int, int], tuple[int, int] | None] = {root: None}
    order = [root]
    queue: deque[tuple[int, int]] = deque([root])
    while queue:
        cx, cy = queue.popleft()
        for n in _passage_neighbors(grid, cx, cy):
            if n not in parent:
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

    return order, subtree


def real_move_reachable(grid, start, *, teleport=None):
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
            moved = slide_path(grid, pos, direction, teleport=teleport)
            if not moved:
                continue
            new_pos = moved[-1]
            if new_pos not in seen:
                seen.add(new_pos)
                frontier.append(new_pos)
    return seen
