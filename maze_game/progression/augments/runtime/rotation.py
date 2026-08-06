"""
rotation.py
-----------
The third maze augment: rotating maze. Every ROTATE_INTERVAL-ish seconds
(see ROTATE_* constants, level-scaled), the whole maze rotates 90 degrees
clockwise -- grid and every entity position transformed together, atomically.

Purely a runtime effect: apply() is a no-op (nothing to do at generation
time), and LabyrinthRun reads augment_build.level_of("rotating_maze")
directly at runtime instead, mirroring the pattern renderer.py's augment
sidebar already uses to read active augment levels independent of
AugmentContext (see augments/runtime/'s package docstring).

For an odd-sized square grid of side `n` (every maze this game generates
is exactly that -- see maze.py's module docstring and
run.py::dimensions_for_maze()), rotate_cell_cw() and rotate_grid_cw() are
mutually consistent and preserve reachability/stoppability exactly: this
is a genuine isometry (same maze, differently oriented), not a topology
change. That's what lets this augment skip every bit of forced-use/
pendant-subtree/seal-pocket machinery the gating/ augments need -- there's
nothing to verify, since rotating can't make the maze any more or less
solvable than it already was.

The actual rotation (mutating LabyrinthRun.grid/player/goal/every entity
position in lockstep, on a timer) lives in progression/run.py -- this
module only owns the augment's registration and the pure coordinate/grid
transform functions, so tests can check those in isolation from the
runtime timer/state-machine plumbing.
"""

from __future__ import annotations

from maze_game.progression.augments import Augment, AugmentContext


class RotatingMazeAugment(Augment):
    id = "rotating_maze"
    name = "Rotating Maze"
    description = (
        "Every couple of seconds, the whole maze spins 90 degrees clockwise -- watch for the warning arrow. "
        "Higher levels rotate faster."
    )

    def apply(self, ctx: AugmentContext) -> None:
        pass  # runtime-only effect -- see this module's docstring


def rotate_cell_cw(cell: tuple[int, int], n: int) -> tuple[int, int]:
    """Rotate a single (x, y) coordinate 90 degrees clockwise within an n x n grid."""
    x, y = cell
    return n - 1 - y, x


def rotate_grid_cw(grid: list[list[int]]) -> list[list[int]]:
    """Rotate an n x n grid 90 degrees clockwise. Returns a new grid; does not mutate the input."""
    n = len(grid)
    return [[grid[n - 1 - x][y] for x in range(n)] for y in range(n)]
