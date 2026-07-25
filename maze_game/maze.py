"""
maze.py
-------
Maze generation and graph utilities.

Current algorithm: Recursive Backtracker (DFS)
  - Produces a perfect maze (no loops, fully connected).
  - Every cell is reachable from every other cell.
  - cols and rows must both be odd.

Planned: Wave Function Collapse generator (drop-in replacement for
`generate_maze` — same signature, same return type).
"""

import random
from collections import deque


def generate_maze(cols: int, rows: int) -> list[list[int]]:
    """
    Return a 2-D grid where 1 = wall and 0 = open passage.

    Uses the recursive-backtracker (DFS) algorithm, carved iteratively with
    an explicit stack rather than Python function-call recursion. A
    call-stack version hits RecursionError around ~100x100 (the default
    sys.getrecursionlimit() of 1000 is exhausted by the carve depth on
    grids that size or larger); an explicit stack scales to arbitrarily
    large grids, bounded only by available memory.

    Both `cols` and `rows` must be odd integers >= 3.
    """
    if cols % 2 == 0 or rows % 2 == 0:
        raise ValueError("cols and rows must both be odd.")

    grid = [[1] * cols for _ in range(rows)]

    # Carve starting from the top-left passage cell.
    grid[1][1] = 0
    stack = [(1, 1)]
    while stack:
        cx, cy = stack[-1]
        directions = [(0, -2), (0, 2), (-2, 0), (2, 0)]
        random.shuffle(directions)
        for dx, dy in directions:
            nx, ny = cx + dx, cy + dy
            if 0 <= nx < cols and 0 <= ny < rows and grid[ny][nx] == 1:
                # Remove the wall between current cell and neighbour.
                grid[cy + dy // 2][cx + dx // 2] = 0
                grid[ny][nx] = 0
                stack.append((nx, ny))
                break
        else:
            # No unvisited neighbour from here -- backtrack.
            stack.pop()

    return grid


def farthest_reachable_cell(
    grid: list[list[int]], start: tuple[int, int]
) -> tuple[int, int]:
    """
    BFS from `start`; return the passage cell with the longest shortest-path
    distance.  Used to place the goal as far from the player as possible.
    """
    cols = len(grid[0])
    rows = len(grid)
    visited = [[False] * cols for _ in range(rows)]

    queue: deque[tuple[int, int]] = deque([start])
    visited[start[1]][start[0]] = True
    farthest = start

    while queue:
        cx, cy = queue.popleft()
        farthest = (cx, cy)
        for dx, dy in ((0, 1), (0, -1), (1, 0), (-1, 0)):
            nx, ny = cx + dx, cy + dy
            if (
                0 <= nx < cols
                and 0 <= ny < rows
                and not visited[ny][nx]
                and grid[ny][nx] == 0
            ):
                visited[ny][nx] = True
                queue.append((nx, ny))

    return farthest
