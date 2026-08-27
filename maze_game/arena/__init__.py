"""
The arena interlude: a one-time 3D (raycast) replay of a run's very first
maze, triggered after the first group of 5 mazes clears. The player's
earlier route shows as a colour trail pointing at the exit; enemies block
the route and treasures sit at far dead-ends off it.

See docs/planning/3d-rework.md for the engine research and phased plan.
``run_arena`` is the entry point progression/app.py hands off to.
"""

from maze_game.arena.app import run_arena
from maze_game.arena.state import ArenaState

__all__ = ["run_arena", "ArenaState"]
