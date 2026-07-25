"""
progression.py
---------------
The labyrinth progression mode: a sequence of LABYRINTH_TOTAL_MAZES mazes,
gradually increasing in size, each with its own time limit. Mazes within a
group of LABYRINTH_GROUP_SIZE advance immediately on completion (no pause);
after the last maze in a group, the run pauses for a break until the player
resumes. Running out of time on any maze ends the whole run -- this was
pitched as a maze *rogue-like*, so failure means starting over from maze 1,
not retrying in place. See docs/progression.md for the reasoning behind
these starting numbers; they're meant to be retuned after playtesting.

Deliberately independent of pygame -- pure state machine, testable without a
display, same pattern as Game/history.py.
"""

import time

from maze_game.constants import (
    LABYRINTH_TOTAL_MAZES, LABYRINTH_GROUP_SIZE,
    LABYRINTH_TIME_BASE, LABYRINTH_TIME_PER_TURN,
    MIN_DIMENSION, MAX_DIMENSION, DIMENSION_STEP,
)
from maze_game.maze import generate_maze, farthest_reachable_cell, shortest_path
from maze_game.player import slide

START_POS: tuple[int, int] = (1, 1)


def dimensions_for_maze(maze_index: int) -> tuple[int, int]:
    """
    maze_index is 1-based (1..LABYRINTH_TOTAL_MAZES). Square mazes: starts
    at MIN_DIMENSION, +DIMENSION_STEP per completed group of
    LABYRINTH_GROUP_SIZE, capped at MAX_DIMENSION.
    """
    group_index = (maze_index - 1) // LABYRINTH_GROUP_SIZE  # 0-based
    size = min(MIN_DIMENSION + group_index * DIMENSION_STEP, MAX_DIMENSION)
    return size, size


def count_direction_changes(path: list[tuple[int, int]]) -> int:
    """
    Number of arrow-key presses a perfect, no-mistakes player would need to
    walk `path` under this game's sliding movement -- a straight run of any
    length costs one press, so this counts direction changes, not cells.
    """
    if len(path) < 2:
        return 0
    presses = 1
    last_dir = (path[1][0] - path[0][0], path[1][1] - path[0][1])
    for i in range(1, len(path) - 1):
        d = (path[i + 1][0] - path[i][0], path[i + 1][1] - path[i][1])
        if d != last_dir:
            presses += 1
            last_dir = d
    return presses


def estimate_time_limit(grid: list[list[int]], start: tuple[int, int], goal: tuple[int, int]) -> float:
    """LABYRINTH_TIME_BASE plus a per-turn budget based on this specific maze's actual shortest path."""
    path = shortest_path(grid, start, goal)
    turns = count_direction_changes(path)
    return LABYRINTH_TIME_BASE + LABYRINTH_TIME_PER_TURN * turns


class LabyrinthRun:
    """
    Owns the full progression state machine: current maze, timing, group
    breaks, and pass/fail. `update()`/`move()` mirror Game's API for the
    currently-active maze; the extra states (on_break, failed,
    completed_run) gate them appropriately.
    """

    def __init__(self) -> None:
        self.maze_index = 1
        self.on_break = False
        self.failed = False
        self.completed_run = False
        self._begin_maze()

    # ── Public API ────────────────────────────────────────────────────────

    def update(self) -> None:
        """Advance the timer and check win/timeout. Call once per frame."""
        if self.on_break or self.failed or self.completed_run or self.finished:
            return
        self.elapsed = time.time() - self._start
        if self.elapsed >= self.time_limit:
            self.elapsed = self.time_limit
            self.failed = True
            return
        if self.player == self.goal:
            self.finished = True
            self._advance()

    def move(self, direction: tuple[int, int]) -> None:
        if self.on_break or self.failed or self.completed_run or self.finished:
            return
        self.player = slide(self.grid, self.player, direction)

    def resume(self) -> None:
        """Leave the post-group break and start the next maze."""
        if not self.on_break:
            return
        self.on_break = False
        self.maze_index += 1
        self._begin_maze()

    def restart(self) -> None:
        """Start the whole run over from maze 1 (e.g. after a timeout failure)."""
        self.maze_index = 1
        self.on_break = False
        self.failed = False
        self.completed_run = False
        self._begin_maze()

    @property
    def group_number(self) -> int:
        """1-based group number for the current maze."""
        return (self.maze_index - 1) // LABYRINTH_GROUP_SIZE + 1

    @property
    def total_groups(self) -> int:
        return -(-LABYRINTH_TOTAL_MAZES // LABYRINTH_GROUP_SIZE)  # ceil division

    # ── Private helpers ───────────────────────────────────────────────────

    def _begin_maze(self) -> None:
        cols, rows = dimensions_for_maze(self.maze_index)
        self.cols, self.rows = cols, rows
        self.grid = generate_maze(cols, rows)
        self.player = START_POS
        self.goal = farthest_reachable_cell(self.grid, START_POS)
        self.time_limit = estimate_time_limit(self.grid, START_POS, self.goal)
        self.elapsed = 0.0
        self.finished = False
        self._start = time.time()

    def _advance(self) -> None:
        if self.maze_index >= LABYRINTH_TOTAL_MAZES:
            self.completed_run = True
        elif self.maze_index % LABYRINTH_GROUP_SIZE == 0:
            self.on_break = True
        else:
            self.maze_index += 1
            self._begin_maze()  # seamless -- no pause within a group
