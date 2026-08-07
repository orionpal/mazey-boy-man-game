"""
fog.py
------
The fourth maze augment: fog of war. Only cells within the player's line
of sight are drawn; LabyrinthRun accumulates everywhere ever seen into
discovered_cells, which -- by the current default -- stays permanently
revealed (see LabyrinthRun.visible_and_discovered_cells()'s docstring for
exactly where to change that later, e.g. to an item-gated "memory").

Purely a runtime/rendering effect: apply() is a no-op (nothing to do at
generation time), same rationale as rotation.py (see augments/runtime/'s
package docstring) -- LabyrinthRun reads
augment_build.level_of("fog_of_war") directly at runtime instead.

Line of sight, for this maze's 1-wide, axis-aligned corridors, is exactly
4 straight rays from the player's cell -- simpler than a radius-limited
BFS and more literally correct: standing in a straight corridor reveals
the whole corridor both directions and nothing else; standing at a
junction reveals partway down every open branch (the ray down each branch
stops the instant the corridor turns, same as real line of sight around a
corner). Deliberately doesn't reuse player.slide_path() -- vision has no
stop-at-junction/teleport/door semantics, it just traces straight lines
until blocked -- so it gets its own small, self-contained helper.

Walks at raw-grid resolution (not passage-cell-to-passage-cell hops, see
_movement.py's _passage_neighbors()), and deliberately includes the wall
cell that terminates each ray: without it, a corridor would render as
though it extended into darkness with no visible boundary, instead of
clearly ending at a wall.
"""

from __future__ import annotations

from maze_game.constants import FOG_PELLET_FREQUENCY_MULTIPLIER, FOG_PELLET_VALUE_MULTIPLIER
from maze_game.progression.augments import Augment, AugmentContext

_DIRECTIONS = ((0, -1), (0, 1), (-1, 0), (1, 0))


class FogOfWarAugment(Augment):
    id = "fog_of_war"
    name = "Fog of War"
    description = (
        "You can only see what's within line of sight -- but once you've discovered a part of the maze, "
        "it stays revealed."
    )
    pellet_frequency_multiplier = FOG_PELLET_FREQUENCY_MULTIPLIER
    pellet_value_multiplier = FOG_PELLET_VALUE_MULTIPLIER

    def apply(self, ctx: AugmentContext) -> None:
        pass  # runtime-only effect -- see this module's docstring


def visible_cells_from(grid: list[list[int]], pos: tuple[int, int]) -> set[tuple[int, int]]:
    """4 straight rays from `pos`, each walked cell-by-cell until (and including) a wall."""
    cols, rows = len(grid[0]), len(grid)
    visible = {pos}
    for dx, dy in _DIRECTIONS:
        x, y = pos
        while True:
            x, y = x + dx, y + dy
            if not (0 <= x < cols and 0 <= y < rows):
                break
            visible.add((x, y))
            if grid[y][x] == 1:
                break  # a wall -- visible (so the corridor's boundary renders), but nothing beyond it
    return visible
