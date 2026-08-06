"""
maze.py
-------
Maze generation and graph utilities.

Algorithm: Growing Tree, carved iteratively with an explicit stack/list
rather than Python function-call recursion (a call-stack version hits
RecursionError around ~100x100 -- the default sys.getrecursionlimit() of
1000 is exhausted by the carve depth on grids that size or larger; an
explicit active-set scales to arbitrarily large grids, bounded only by
available memory).

Growing Tree is a generalization that covers a whole family of maze
algorithms via one parameter, `newest_prob`:
  - newest_prob=1.0 -> always extend the most recently carved cell. This is
    exactly the recursive backtracker (DFS) this replaced: long, winding,
    low-branching corridors.
  - newest_prob=0.0 -> always extend a uniformly random cell from the
    active set (closer to randomized Prim's): many short branches, much
    higher junction density.
  - values in between blend continuously.

Measured empirically (see docs/maze-generation.md) on 21x21 mazes, 200
trials each: the old DFS default put ~5% of open cells at a junction (3+
open neighbours); newest_prob=0.5 roughly doubles that to ~10%, and
stacking the optional `braid()` pass on top pushes it further by converting
some dead ends into loops.

Both `cols` and `rows` must be odd, as before -- passage cells sit on odd
(x, y), walls between them at the even midpoint.
"""

import random
from collections import deque

DEFAULT_NEWEST_PROB = 0.4
DEFAULT_BRAID_PROB = 0.25


def generate_maze(
    cols: int,
    rows: int,
    newest_prob: float = DEFAULT_NEWEST_PROB,
    braid_prob: float = DEFAULT_BRAID_PROB,
    rng: random.Random | None = None,
) -> list[list[int]]:
    """
    Return a 2-D grid where 1 = wall and 0 = open passage.

    `newest_prob` controls branching density (see module docstring); the
    default of 0.4 was chosen empirically to roughly double the junction
    density of the original DFS carver (newest_prob=1.0) while still
    keeping some long-corridor character, rather than going fully uniform.

    `braid_prob` is the probability of converting each dead end into a loop
    by knocking down one more wall (see `braid()`); 0 leaves a pure "perfect
    maze" (a spanning tree, no loops). Braiding does not affect
    connectivity -- it only adds extra edges to an already-connected graph.

    `rng` is an optional `random.Random` instance for reproducible/seeded
    generation; defaults to the `random` module itself (which exposes the
    same method surface as a `Random` instance), so every existing call site
    keeps working unchanged via the global `random.seed()` pattern the tests
    already rely on.

    Both `cols` and `rows` must be odd integers >= 3.
    """
    if cols % 2 == 0 or rows % 2 == 0:
        raise ValueError("cols and rows must both be odd.")
    rng = rng if rng is not None else random

    grid = [[1] * cols for _ in range(rows)]

    # Carve starting from the top-left passage cell.
    grid[1][1] = 0
    active = [(1, 1)]
    while active:
        idx = len(active) - 1 if rng.random() < newest_prob else rng.randrange(len(active))
        cx, cy = active[idx]
        directions = [(0, -2), (0, 2), (-2, 0), (2, 0)]
        rng.shuffle(directions)
        carved = False
        for dx, dy in directions:
            nx, ny = cx + dx, cy + dy
            if 0 <= nx < cols and 0 <= ny < rows and grid[ny][nx] == 1:
                # Remove the wall between current cell and neighbour.
                grid[cy + dy // 2][cx + dx // 2] = 0
                grid[ny][nx] = 0
                active.append((nx, ny))
                carved = True
                break
        if not carved:
            # No unvisited neighbour from here -- drop it from the active set.
            active.pop(idx)

    if braid_prob > 0:
        grid = braid(grid, braid_prob, rng=rng)

    return grid


def braid(grid: list[list[int]], p: float, rng: random.Random | None = None) -> list[list[int]]:
    """
    Post-process pass: for each dead end (a passage cell with exactly one
    open neighbour), with probability `p`, knock down one more wall to a
    neighbouring cell -- turning that dead end into a through-passage or
    junction. This introduces loops (the result is no longer a spanning
    tree), which only ever *adds* reachability, never removes it, so a
    fully-connected input stays fully connected.

    `rng` is an optional `random.Random` instance for reproducible/seeded
    generation; defaults to the `random` module (see `generate_maze`).

    Returns a new grid; does not mutate the input.
    """
    rng = rng if rng is not None else random
    grid = [row[:] for row in grid]
    cols, rows = len(grid[0]), len(grid)
    cells = [(x, y) for y in range(1, rows, 2) for x in range(1, cols, 2)]
    dead_ends = [
        (x, y) for x, y in cells if grid[y][x] == 0 and _open_neighbour_count(grid, x, y) == 1
    ]
    rng.shuffle(dead_ends)

    for x, y in dead_ends:
        if rng.random() > p:
            continue
        if _open_neighbour_count(grid, x, y) != 1:
            continue  # an earlier carve in this pass may have already opened this one up

        candidates = []
        for dx, dy in ((0, -2), (0, 2), (-2, 0), (2, 0)):
            nx, ny = x + dx, y + dy
            wx, wy = x + dx // 2, y + dy // 2
            # The neighbour *cell* is always already carved open by this
            # point (every odd-coordinate cell gets visited during
            # generation) -- what matters is whether the wall segment
            # between here and the neighbour is still closed.
            if 0 <= nx < cols and 0 <= ny < rows and grid[wy][wx] == 1:
                if _opening_isolates_a_wall_pillar(grid, wx, wy):
                    continue  # would carve a 1-cell loop around a single wall pixel
                candidates.append((wx, wy))

        if candidates:
            wx, wy = rng.choice(candidates)
            grid[wy][wx] = 0

    return grid


def _opening_isolates_a_wall_pillar(grid: list[list[int]], seg_x: int, seg_y: int) -> bool:
    """
    True if carving the wall segment at (seg_x, seg_y) would leave either of
    its two neighbouring even,even grid intersections fully surrounded by
    open cells on all 4 sides -- a single standalone wall pixel with a
    1-cell loop running all the way around it. Only possible via braid()
    (the base spanning tree has no cycles at all, so this never occurs
    before braiding); rejecting it here keeps braid's extra connections
    from producing that specific pattern.
    """
    cols, rows = len(grid[0]), len(grid)
    # The wall segment sits between two even,even intersections -- to its
    # left/right if it's a vertical connector (odd x, even y), or above/below
    # if it's a horizontal connector (even x, odd y).
    if seg_x % 2 == 1:
        intersections = [(seg_x - 1, seg_y), (seg_x + 1, seg_y)]
    else:
        intersections = [(seg_x, seg_y - 1), (seg_x, seg_y + 1)]

    for ix, iy in intersections:
        if not (0 <= ix < cols and 0 <= iy < rows):
            continue
        fully_open_if_carved = True
        for dx, dy in ((0, 1), (0, -1), (1, 0), (-1, 0)):
            nx, ny = ix + dx, iy + dy
            if (nx, ny) == (seg_x, seg_y):
                continue  # about to be carved open
            if not (0 <= nx < cols and 0 <= ny < rows) or grid[ny][nx] != 0:
                fully_open_if_carved = False
                break
        if fully_open_if_carved:
            return True
    return False


def _open_neighbour_count(grid: list[list[int]], cx: int, cy: int) -> int:
    cols, rows = len(grid[0]), len(grid)
    return sum(
        1
        for dx, dy in ((0, 1), (0, -1), (1, 0), (-1, 0))
        if 0 <= cx + dx < cols and 0 <= cy + dy < rows and grid[cy + dy][cx + dx] == 0
    )


def is_stoppable_cell(grid: list[list[int]], x: int, y: int) -> bool:
    """
    True if `player.slide()` can actually stop on this cell -- a wall ahead
    (dead end, 1 open neighbour) or a junction (3+ open neighbours). A plain
    2-open-neighbour corridor/turn cell can never be landed on, since the
    slide always continues straight through it. Extracted from
    `farthest_reachable_cell`'s inline rule so other code (e.g. maze
    augments placing goal/teleporter cells) doesn't reimplement -- and risk
    drifting from -- this same, already-once-buggy rule.
    """
    return _open_neighbour_count(grid, x, y) != 2


def bfs_reachable(grid: list[list[int]], start: tuple[int, int]) -> set[tuple[int, int]]:
    """
    Return every open cell reachable from `start` via 4-directional
    adjacency. General-purpose connectivity primitive used by generation-time
    correctness checks (e.g. verifying a maze augment's grid mutation hasn't
    fragmented the main region).
    """
    cols, rows = len(grid[0]), len(grid)
    seen = {start}
    queue: deque[tuple[int, int]] = deque([start])
    while queue:
        cx, cy = queue.popleft()
        for dx, dy in ((0, 1), (0, -1), (1, 0), (-1, 0)):
            nx, ny = cx + dx, cy + dy
            if (
                0 <= nx < cols
                and 0 <= ny < rows
                and grid[ny][nx] == 0
                and (nx, ny) not in seen
            ):
                seen.add((nx, ny))
                queue.append((nx, ny))
    return seen


def farthest_reachable_cell(
    grid: list[list[int]],
    start: tuple[int, int],
    extra_edges: dict[tuple[int, int], tuple[int, int]] | None = None,
    candidates: set[tuple[int, int]] | None = None,
) -> tuple[int, int]:
    """
    BFS from `start`; return the *reachable-via-sliding* passage cell with
    the longest shortest-path distance. Used to place the goal as far from
    the player as possible.

    "Reachable-via-sliding" specifically excludes cells with exactly 2 open
    neighbours (a straight or turning mid-corridor cell): player.slide()
    only ever stops at a wall ahead or a junction (3+ open neighbours), so a
    2-neighbour cell can never be landed on -- the player always slides
    straight through it. Picking one as the goal made the maze
    unsolvable (confirmed empirically: ~18% of generated mazes before this
    fix). BFS still visits every cell in the usual non-decreasing-distance
    order; this just restricts which visited cell counts as a candidate
    "farthest" answer to ones the sliding mechanic can actually stop on.

    `extra_edges` adds non-grid traversable edges on top of ordinary
    4-directional adjacency (see `shortest_path`'s identical parameter) --
    lets goal placement account for teleporter shortcuts instead of only
    ever seeing plain grid distance.

    `candidates`, if given, further restricts which visited cell can be
    picked as "farthest" to this set (on top of the stoppable-cell rule
    above) -- used to confine goal placement to cells behind an augment's
    mandatory chain, without also restricting *traversal* to that set (the
    BFS still walks the whole grid; only the answer is filtered). Confining
    traversal itself was tried and rejected: restricted to only stoppable
    cells, the single-hop adjacency graph is almost entirely disconnected,
    so the walk could barely leave its starting pocket regardless of the
    maze's actual size.
    """
    cols = len(grid[0])
    rows = len(grid)
    visited = [[False] * cols for _ in range(rows)]

    queue: deque[tuple[int, int]] = deque([start])
    visited[start[1]][start[0]] = True
    farthest = start

    while queue:
        cx, cy = queue.popleft()
        if _open_neighbour_count(grid, cx, cy) != 2 and (candidates is None or (cx, cy) in candidates):
            farthest = (cx, cy)
        neighbours = [(cx + dx, cy + dy) for dx, dy in ((0, 1), (0, -1), (1, 0), (-1, 0))]
        linked = (extra_edges or {}).get((cx, cy))
        if linked is not None:
            neighbours.append(linked)
        for nx, ny in neighbours:
            if (
                0 <= nx < cols
                and 0 <= ny < rows
                and not visited[ny][nx]
                and grid[ny][nx] == 0
            ):
                visited[ny][nx] = True
                queue.append((nx, ny))

    return farthest


def shortest_path(
    grid: list[list[int]],
    start: tuple[int, int],
    goal: tuple[int, int],
    extra_edges: dict[tuple[int, int], tuple[int, int]] | None = None,
) -> list[tuple[int, int]]:
    """
    BFS shortest path from `start` to `goal`, inclusive of both ends.
    Used by the labyrinth progression mode to estimate a fair per-maze time
    limit from the actual generated maze rather than a size-only guess.

    `extra_edges` adds non-grid traversable edges on top of ordinary
    4-directional adjacency (e.g. a teleporter map: `{cell: linked_cell}`) --
    needed once a maze augment can make the goal reachable only *through*
    such an edge, since plain grid adjacency alone would never find a path
    to it.
    """
    extra_edges = extra_edges or {}
    cols, rows = len(grid[0]), len(grid)
    prev: dict[tuple[int, int], tuple[int, int] | None] = {start: None}
    queue: deque[tuple[int, int]] = deque([start])

    while queue:
        cx, cy = queue.popleft()
        if (cx, cy) == goal:
            break
        neighbours = [
            (cx + dx, cy + dy) for dx, dy in ((0, 1), (0, -1), (1, 0), (-1, 0))
        ]
        linked = extra_edges.get((cx, cy))
        if linked is not None:
            neighbours.append(linked)
        for nx, ny in neighbours:
            if (
                0 <= nx < cols
                and 0 <= ny < rows
                and grid[ny][nx] == 0
                and (nx, ny) not in prev
            ):
                prev[(nx, ny)] = (cx, cy)
                queue.append((nx, ny))

    path = [goal]
    while prev[path[-1]] is not None:
        path.append(prev[path[-1]])
    path.reverse()
    return path
