"""
entities/__init__.py
---------------------
Shared base for anything placed in a maze that the player can contact
mid-slide (pellets, hazards), plus the single dispatcher LabyrinthRun.move()
calls to resolve contact against all of them -- this keeps entity-specific
knowledge out of progression/run.py. Concrete entity types live in sibling
modules (hazards.py) and are imported directly by callers that need them;
this module only holds what's shared.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from maze_game.constants import C_HAZARD

if TYPE_CHECKING:
    from maze_game.progression.run import LabyrinthRun


class MazeEntity:
    """Base for anything placed in the maze grid the player can contact via slide_path()."""

    def __init__(self, pos: tuple[int, int]) -> None:
        self.pos = pos

    def on_contact(self, run: "LabyrinthRun") -> None:
        raise NotImplementedError


def open_cells(grid: list[list[int]]) -> list[tuple[int, int]]:
    """Every passage cell in `grid` -- shared placement primitive for hazards.py/shop_tile.py's spawn_*() functions."""
    return [(x, y) for y, row in enumerate(grid) for x, val in enumerate(row) if val == 0]


def apply_time_penalty(run: "LabyrinthRun", amount: float, pos: tuple[int, int]) -> None:
    """Shared time-cost helper used by Hazard.on_contact."""
    run.time.spend(amount)
    run.add_popup(pos, f"-{amount:.1f}s", C_HAZARD)
    run.events.append("hazard_hit")


def resolve_contacts(run: "LabyrinthRun", path: list[tuple[int, int]]) -> None:
    """
    Check every cell the player's slide just passed through against
    pellets, gold pellets, keys, and hazards, applying effects in order.
    Pellets, gold pellets, and keys are removed from their lists on
    collection (one-time pickups); hazards persist and can be hit again
    on a later, separate move.
    """
    for cell in path:
        remaining = []
        for pellet in run.pellets:
            if pellet.pos == cell:
                pellet.on_contact(run)
            else:
                remaining.append(pellet)
        run.pellets = remaining

        remaining_gold = []
        for gold_pellet in run.gold_pellets:
            if gold_pellet.pos == cell:
                gold_pellet.on_contact(run)
            else:
                remaining_gold.append(gold_pellet)
        run.gold_pellets = remaining_gold

        remaining_keys = []
        for key in run.keys:
            if key.pos == cell:
                key.on_contact(run)
            else:
                remaining_keys.append(key)
        run.keys = remaining_keys

        remaining_shop_tiles = []
        for shop_tile in run.shop_tiles:
            if shop_tile.pos == cell:
                shop_tile.on_contact(run)
            else:
                remaining_shop_tiles.append(shop_tile)
        run.shop_tiles = remaining_shop_tiles

        for hazard in run.hazards:
            if hazard.pos == cell:
                hazard.on_contact(run)
