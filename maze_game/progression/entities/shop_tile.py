"""
shop_tile.py
------------
The walk-to shop: a second way to spend gold, inside a maze rather than
only between runs at the Base (progression/meta/). Placement mirrors
GoldPellet exactly (spawn_shop_tile() is spawn_gold_pellets() with a
different entity type) -- a `chance` chance of exactly one per maze, on a
random open cell excluding start/goal/every other already-placed entity.

Unlike every other entity's on_contact(), ShopTile doesn't apply its effect
immediately -- it hands off to LabyrinthRun.enter_shop(), which pauses the
real time resource and starts a second, independent countdown
(SHOP_PAUSE_SECONDS) for the in-maze shop screen (progression/shop/'s
MAZE_SHOP_ITEMS catalog, purchased via LabyrinthRun.buy_shop_item()). The
tile is a one-time pickup (removed from run.shop_tiles on contact, same as
GoldPellet) -- it opens the shop once per maze, not once per step.
"""

from __future__ import annotations

import random
from typing import TYPE_CHECKING

from maze_game.constants import SHOP_TILE_SPAWN_CHANCE
from maze_game.progression.entities import MazeEntity, open_cells

if TYPE_CHECKING:
    from maze_game.progression.run import LabyrinthRun


class ShopTile(MazeEntity):
    def on_contact(self, run: "LabyrinthRun") -> None:
        run.enter_shop()


def spawn_shop_tile(
    grid: list[list[int]],
    exclude: set[tuple[int, int]],
    chance: float = SHOP_TILE_SPAWN_CHANCE,
    rng: random.Random | None = None,
) -> list[ShopTile]:
    """A maze has a `chance` chance of containing exactly one shop tile -- same shape as spawn_gold_pellets()."""
    rng = rng if rng is not None else random
    if rng.random() >= chance:
        return []
    candidates = [c for c in open_cells(grid) if c not in exclude]
    if not candidates:
        return []
    return [ShopTile(rng.choice(candidates))]
