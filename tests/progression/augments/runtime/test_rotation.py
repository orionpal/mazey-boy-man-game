"""
Tests for maze_game.progression.augments.runtime.rotation -- the pure
coordinate/grid transform functions. RotatingMazeAugment's apply() is a
no-op (see the module docstring), so there's nothing to test there beyond
registration (covered by test_pipeline.py-style registry tests
elsewhere); LabyrinthRun._rotate_maze()'s runtime wiring (entity
transforms, timer gating) is tested in tests/progression/test_run.py.
"""

import random

from maze_game.maze import bfs_reachable, generate_maze, is_stoppable_cell
from maze_game.progression.augments.runtime.rotation import rotate_cell_cw, rotate_grid_cw


def test_rotate_cell_cw_four_times_is_identity():
    n = 9
    cell = (3, 5)
    for _ in range(4):
        cell = rotate_cell_cw(cell, n)
    assert cell == (3, 5)


def test_rotate_grid_cw_four_times_is_identity():
    grid = generate_maze(9, 9, rng=random.Random(1))
    rotated = grid
    for _ in range(4):
        rotated = rotate_grid_cw(rotated)
    assert rotated == grid


def test_rotate_grid_cw_and_rotate_cell_cw_are_mutually_consistent():
    """rotate_grid_cw(grid)[ny][nx] must equal grid[y][x] wherever rotate_cell_cw maps (x, y) -> (nx, ny)."""
    n = 9
    grid = generate_maze(n, n, rng=random.Random(2))
    rotated = rotate_grid_cw(grid)
    for y in range(n):
        for x in range(n):
            nx, ny = rotate_cell_cw((x, y), n)
            assert rotated[ny][nx] == grid[y][x]


def test_rotate_grid_cw_preserves_reachability():
    n = 21
    grid = generate_maze(n, n, rng=random.Random(3))
    start = (1, 1)
    reachable = bfs_reachable(grid, start)

    rotated = rotate_grid_cw(grid)
    rotated_start = rotate_cell_cw(start, n)
    rotated_reachable = bfs_reachable(rotated, rotated_start)

    assert rotated_reachable == {rotate_cell_cw(c, n) for c in reachable}


def test_rotate_grid_cw_preserves_stoppability():
    """A rotation is an isometry -- a cell's open-neighbour count (and so whether player.slide() can stop there) can't change."""
    n = 21
    grid = generate_maze(n, n, rng=random.Random(4))
    rotated = rotate_grid_cw(grid)
    for y in range(n):
        for x in range(n):
            nx, ny = rotate_cell_cw((x, y), n)
            assert is_stoppable_cell(grid, x, y) == is_stoppable_cell(rotated, nx, ny)
