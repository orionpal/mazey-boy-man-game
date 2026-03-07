"""
game.py
-------
Core game state and logic.

The Game class owns the maze grid, player position, goal position, and
timer.  It delegates maze generation to `maze.py` and movement to
`player.py`, keeping each concern in one place.
"""

import time

from maze_game.constants import COLS, ROWS
from maze_game.maze import generate_maze, farthest_reachable_cell, random_cell
from maze_game.player import slide

# The player always starts at the top-left passage cell.
START_POS: tuple[int, int] = (1, 1)


class Game:
    """Holds all mutable game state and exposes update / move / new_maze."""

    def __init__(self) -> None:
        self.best_time: float | None = None
        # Kick off the first maze immediately.
        self.new_maze()

    # ── Public API ────────────────────────────────────────────────────────

    def new_maze(self) -> None:
        """Generate a fresh maze and reset round state."""
        self.grid      = generate_maze(COLS, ROWS)
        self.player    = START_POS
        self.goal      = random_cell(self.grid)
        self.elapsed   = 0.0
        self.finished  = False
        self._start    = time.time()

    def update(self) -> None:
        """Advance the timer and check win condition. Call once per frame."""
        if self.finished:
            return
        self.elapsed = time.time() - self._start
        if self.player == self.goal:
            self.finished = True
            if self.best_time is None or self.elapsed < self.best_time:
                self.best_time = self.elapsed

    def move(self, direction: tuple[int, int]) -> None:
        """Slide the player in `direction` (ignored after the maze is solved)."""
        if self.finished:
            return
        self.player = slide(self.grid, self.player, direction)
