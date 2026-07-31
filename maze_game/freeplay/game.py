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
from maze_game.freeplay.history import RunRecord, new_record, load_history, append_record, DEFAULT_HISTORY_PATH

# The player always starts at the top-left passage cell.
START_POS: tuple[int, int] = (1, 1)


class Game:
    """Holds all mutable game state and exposes update / move / new_maze."""

    def __init__(self, history_path: Path = DEFAULT_HISTORY_PATH) -> None:
        self.cols = DEFAULT_COLS
        self.rows = DEFAULT_ROWS
        self.history_path = history_path
        self.history: list[RunRecord] = load_history(history_path)
        # Event-name strings for mvp_main.py/freeplay/app.py to play sounds
        # for -- see docs/assets.md. Drained once per frame by the loop, not
        # reset by new_maze() (it's a per-frame buffer, not round state).
        self.events: list[str] = []
        # Kick off the first maze immediately.
        self.new_maze()

    # ── Public API ────────────────────────────────────────────────────────

    @property
    def best_time(self) -> float | None:
        """
        Shortest recorded time for the *current* dimensions, across this and
        past sessions (derived from `history`, which is persisted to disk and
        loaded on startup -- there is no separately-tracked best_time value
        to fall out of sync with it).

        Previously this was a single value tracked across all dimensions and
        only within the current session, which meant: (a) it wasn't
        dimension-specific, so switching maze size could show an unrelated
        size's time as "best", and (b) it reset to None on every restart, so
        it could show a worse time as "best" than what was actually in your
        history from an earlier session.
        """
        times = [r.seconds for r in self.history if r.cols == self.cols and r.rows == self.rows]
        return min(times) if times else None

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
            record = new_record(self.cols, self.rows, self.elapsed)
            self.history = append_record(self.history, record, self.history_path)
            self.events.append("maze_complete")

    def move(self, direction: tuple[int, int]) -> None:
        """Slide the player in `direction` (ignored after the maze is solved)."""
        if self.finished:
            return
        new_pos = slide(self.grid, self.player, direction)
        if new_pos != self.player:
            self.events.append("move")
        self.player = new_pos


def _clamp_odd(value: int) -> int:
    """Clamp to [MIN_DIMENSION, MAX_DIMENSION] and force odd (round down)."""
    value = max(MIN_DIMENSION, min(MAX_DIMENSION, value))
    if value % 2 == 0:
        value -= 1
    return value
