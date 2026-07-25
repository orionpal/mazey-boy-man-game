"""
Tests for maze_game.maze — generation correctness, connectivity, and
scalability (no reliance on Python's recursion limit).
"""

import random

import pytest

from maze_game.maze import generate_maze, farthest_reachable_cell

SIZES = [5, 9, 21, 51]


def _open_cells(grid):
    return [
        (x, y)
        for y, row in enumerate(grid)
        for x, val in enumerate(row)
        if val == 0
    ]


def _reachable_from(grid, start):
    """BFS reachability set from `start` (mirrors farthest_reachable_cell's traversal)."""
    from collections import deque

    cols, rows = len(grid[0]), len(grid)
    seen = {start}
    q = deque([start])
    while q:
        cx, cy = q.popleft()
        for dx, dy in ((0, 1), (0, -1), (1, 0), (-1, 0)):
            nx, ny = cx + dx, cy + dy
            if (
                0 <= nx < cols
                and 0 <= ny < rows
                and grid[ny][nx] == 0
                and (nx, ny) not in seen
            ):
                seen.add((nx, ny))
                q.append((nx, ny))
    return seen


@pytest.mark.parametrize("size", SIZES)
def test_generate_maze_shape(size):
    grid = generate_maze(size, size)
    assert len(grid) == size
    assert all(len(row) == size for row in grid)


@pytest.mark.parametrize("size", SIZES)
def test_generate_maze_is_binary(size):
    grid = generate_maze(size, size)
    values = {val for row in grid for val in row}
    assert values <= {0, 1}


def test_generate_maze_rejects_even_dimensions():
    with pytest.raises(ValueError):
        generate_maze(20, 21)
    with pytest.raises(ValueError):
        generate_maze(21, 20)


@pytest.mark.parametrize("size", SIZES)
def test_generate_maze_is_fully_connected(size):
    """
    A 'perfect maze' (recursive backtracker) must connect every open cell
    reachable from the carve origin. This is the property the game relies
    on to guarantee the goal is always reachable.
    """
    grid = generate_maze(size, size)
    open_cells = set(_open_cells(grid))
    reachable = _reachable_from(grid, (1, 1))
    assert reachable == open_cells


@pytest.mark.parametrize("size", SIZES)
def test_generate_maze_has_no_2x2_open_blocks(size):
    """
    A 'perfect maze' should have no open rooms/loops -- every 2x2 block of
    cells should contain at least one wall. This is what gives the maze its
    corridor-like, no-loops structure (a spanning tree, not a general graph).
    """
    grid = generate_maze(size, size)
    for y in range(size - 1):
        for x in range(size - 1):
            block = (grid[y][x], grid[y][x + 1], grid[y + 1][x], grid[y + 1][x + 1])
            assert block != (0, 0, 0, 0), f"open 2x2 block at ({x},{y})"


def test_generate_maze_deterministic_with_seeded_random():
    random.seed(1234)
    a = generate_maze(21, 21)
    random.seed(1234)
    b = generate_maze(21, 21)
    assert a == b


@pytest.mark.parametrize("size", [51, 101, 151, 201])
def test_generate_maze_scales_past_recursion_limit(size):
    """
    Regression test: the original recursive-backtracker implementation used
    Python function-call recursion to carve, which raised RecursionError for
    grids around 101x101 and larger (roughly >~500 open cells with the
    default sys.getrecursionlimit()). Generation must not depend on Python's
    call stack depth, however large the grid.
    """
    grid = generate_maze(size, size)
    assert len(grid) == size


def test_farthest_reachable_cell_is_open_and_far():
    grid = generate_maze(21, 21)
    start = (1, 1)
    goal = farthest_reachable_cell(grid, start)
    assert grid[goal[1]][goal[0]] == 0
    assert goal != start


def test_farthest_reachable_cell_is_actually_the_farthest():
    """farthest_reachable_cell should match a from-scratch BFS distance computation."""
    from collections import deque

    grid = generate_maze(21, 21)
    start = (1, 1)
    cols, rows = len(grid[0]), len(grid)

    dist = {start: 0}
    q = deque([start])
    while q:
        cx, cy = q.popleft()
        for dx, dy in ((0, 1), (0, -1), (1, 0), (-1, 0)):
            nx, ny = cx + dx, cy + dy
            if (
                0 <= nx < cols
                and 0 <= ny < rows
                and grid[ny][nx] == 0
                and (nx, ny) not in dist
            ):
                dist[(nx, ny)] = dist[(cx, cy)] + 1
                q.append((nx, ny))

    expected_max = max(dist.values())
    goal = farthest_reachable_cell(grid, start)
    assert dist[goal] == expected_max
