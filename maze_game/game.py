"""
game.py
-------
Core game state and logic.

The Game class owns the maze grid, player position, goal position, timer,
adjustable dimensions, and the run-history log. It delegates maze generation
to `maze.py` and movement to `player.py`, keeping each concern in one place.
"""

import time
from pathlib import Path

from maze_game.constants import DEFAULT_COLS, DEFAULT_ROWS, MIN_DIMENSION, MAX_DIMENSION, DIMENSION_STEP
from maze_game.maze import generate_maze, farthest_reachable_cell
from maze_game.player import slide
from maze_game.history import RunRecord, new_record, load_history, append_record, DEFAULT_HISTORY_PATH

# The player always starts at the top-left passage cell.
START_POS: tuple[int, int] = (1, 1)


class Game:
    """Holds all mutable game state and exposes update / move / new_maze."""

    def __init__(self, history_path: Path = DEFAULT_HISTORY_PATH) -> None:
        self.cols = DEFAULT_COLS
        self.rows = DEFAULT_ROWS
        self.best_time: float | None = None
        self.history_path = history_path
        self.history: list[RunRecord] = load_history(history_path)
        # Kick off the first maze immediately.
        self.new_maze()

    # ── Public API ────────────────────────────────────────────────────────

    def new_maze(self) -> None:
        """Generate a fresh maze and reset round state."""
        self.grid      = generate_maze(self.cols, self.rows)
        self.player    = START_POS
        self.goal      = farthest_reachable_cell(self.grid, START_POS)
        self.elapsed   = 0.0
        self.finished  = False
        self._start    = time.time()

    def set_dimensions(self, cols: int, rows: int) -> None:
        """
        Change grid size and start a new maze at the new size. Values are
        clamped to [MIN_DIMENSION, MAX_DIMENSION] and forced odd (required
        by the maze carver) before applying.
        """
        self.cols = _clamp_odd(cols)
        self.rows = _clamp_odd(rows)
        self.new_maze()

    def adjust_cols(self, delta_steps: int) -> None:
        """Nudge column count by `delta_steps` increments of DIMENSION_STEP (e.g. +1/-1)."""
        self.set_dimensions(self.cols + delta_steps * DIMENSION_STEP, self.rows)

    def adjust_rows(self, delta_steps: int) -> None:
        """Nudge row count by `delta_steps` increments of DIMENSION_STEP (e.g. +1/-1)."""
        self.set_dimensions(self.cols, self.rows + delta_steps * DIMENSION_STEP)

    def update(self) -> None:
        """Advance the timer and check win condition. Call once per frame."""
        if self.finished:
            return
        self.elapsed = time.time() - self._start
        if self.player == self.goal:
            self.finished = True
            if self.best_time is None or self.elapsed < self.best_time:
                self.best_time = self.elapsed
            record = new_record(self.cols, self.rows, self.elapsed)
            self.history = append_record(self.history, record, self.history_path)

    def move(self, direction: tuple[int, int]) -> None:
        """Slide the player in `direction` (ignored after the maze is solved)."""
        if self.finished:
            return
        self.player = slide(self.grid, self.player, direction)


def _clamp_odd(value: int) -> int:
    """Clamp to [MIN_DIMENSION, MAX_DIMENSION] and force odd (round down)."""
    value = max(MIN_DIMENSION, min(MAX_DIMENSION, value))
    if value % 2 == 0:
        value -= 1
    return value
