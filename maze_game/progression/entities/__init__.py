"""
entities/__init__.py
---------------------
Shared base for anything placed in a maze that the player can contact
mid-slide (pellets, enemies), plus the single dispatcher LabyrinthRun.move()
calls to resolve contact against all of them -- this keeps entity-specific
knowledge out of progression/run.py. Concrete entity types live in sibling
modules (hazards.py) and are imported directly by callers that need them;
this module only holds what's shared.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from maze_game.constants import C_ENEMY

if TYPE_CHECKING:
    from maze_game.progression.run import LabyrinthRun


class MazeEntity:
    """Base for anything placed in the maze grid the player can contact via slide_path()."""

    def __init__(self, pos: tuple[int, int]) -> None:
        self.pos = pos

    def on_contact(self, run: "LabyrinthRun") -> None:
        raise NotImplementedError


def apply_time_penalty(run: "LabyrinthRun", amount: float, pos: tuple[int, int]) -> None:
    """Shared time-cost helper used by Enemy.on_contact."""
    run.time.spend(amount)
    run.add_popup(pos, f"-{amount:.1f}s", C_ENEMY)
    run.events.append("enemy_hit")


def resolve_contacts(run: "LabyrinthRun", path: list[tuple[int, int]]) -> None:
    """
    Check every cell the player's slide just passed through against
    pellets, gold pellets, and enemies, applying effects in order. Pellets
    and gold pellets are removed from their lists on collection (one-time
    pickups); enemies are a persistent hazard that can be hit again on a
    later, separate move.
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

        for enemy in run.enemies:
            if enemy.pos == cell:
                enemy.on_contact(run)
