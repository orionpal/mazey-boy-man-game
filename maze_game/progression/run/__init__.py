"""
progression/run/ -- the labyrinth progression state machine, split along
its natural seams (was a single 567-line run.py, over the repo's 400-line
cap):

- ``model.py``  -- value types + pure pacing math (TimeResource,
  FirstMazeRecord, Popup, dimensions_for_maze, _breaks_due_after).
- ``breaks.py`` -- everything about the pauses between mazes
  (BreakSequenceMixin: shop / augment / arena / in-maze shop tile + the
  break queue).
- ``state.py``  -- the LabyrinthRun class itself (per-maze setup, movement,
  the per-frame update loop).

Public API is unchanged -- import the same names from
``maze_game.progression.run`` as before.
"""

from maze_game.progression.run.model import (
    TimeResource, FirstMazeRecord, Popup, START_POS,
    dimensions_for_maze, is_milestone_maze,
)
from maze_game.progression.run.state import LabyrinthRun

__all__ = [
    "LabyrinthRun", "TimeResource", "FirstMazeRecord", "Popup", "START_POS",
    "dimensions_for_maze", "is_milestone_maze",
]
