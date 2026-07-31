"""
perks.py
--------
Passive perks -- the shop break's card pool -- and the Build that
accumulates them. `magnitude` is added (not multiplied) on each pick:
both current perks grant a charge/bonus count (enemy contacts ignored,
gold awarded), not a rate, so stacking is additive.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from maze_game.constants import (
    ENEMY_SHIELD_CHARGES_PER_LEVEL, GOLD_RUSH_BONUS_PER_LEVEL,
)


@dataclass(frozen=True)
class Perk:
    id: str
    name: str
    description: str
    effect_key: str
    magnitude: float


class Build:
    """The player's accumulated perks for this run -- reset on death (LabyrinthRun.restart())."""

    def __init__(self) -> None:
        self.picks: dict[str, int] = {}
        # Still read directly by spawn_pellets()/Pellet.on_contact() -- no
        # perk sets these away from 1.0 anymore, but they stay as the
        # multipliers those call sites expect.
        self.pellet_frequency_multiplier = 1.0
        self.pellet_value_multiplier = 1.0
        # No in-run Perk uses this effect_key yet -- it exists for
        # progression/meta/'s "enemy resistance" upgrade, seeded onto a
        # fresh Build before the run starts (see MetaProgress.seed_build()).
        self.enemy_resistance_multiplier = 1.0
        # Bulwark: ignored enemy contacts, refilled to this count every maze
        # (see LabyrinthRun._begin_maze()'s shield_charges_remaining reset).
        self.enemy_shield_charges_per_maze = 0
        # Speedrunner: bonus gold awarded alongside the existing automatic
        # time bonus on an under-par maze clear.
        self.gold_rush_bonus = 0

    def acquire(self, perk: Perk) -> None:
        self.picks[perk.id] = self.picks.get(perk.id, 0) + 1
        EFFECTS[perk.effect_key](self, perk.magnitude)


def _apply_pellet_frequency(build: Build, magnitude: float) -> None:
    build.pellet_frequency_multiplier *= magnitude


def _apply_pellet_value(build: Build, magnitude: float) -> None:
    build.pellet_value_multiplier *= magnitude


def _apply_enemy_resistance(build: Build, magnitude: float) -> None:
    build.enemy_resistance_multiplier *= magnitude


def _apply_enemy_shield(build: Build, magnitude: float) -> None:
    build.enemy_shield_charges_per_maze += int(magnitude)


def _apply_gold_rush(build: Build, magnitude: float) -> None:
    build.gold_rush_bonus += int(magnitude)


EFFECTS: dict[str, Callable[[Build, float], None]] = {
    "pellet_frequency": _apply_pellet_frequency,
    "pellet_value": _apply_pellet_value,
    "enemy_resistance": _apply_enemy_resistance,
    "enemy_shield": _apply_enemy_shield,
    "gold_rush": _apply_gold_rush,
}

ALL_PERKS: list[Perk] = [
    Perk(
        id="enemy_shield", name="Bulwark",
        description="Ignore the first enemy contact each maze.",
        effect_key="enemy_shield", magnitude=ENEMY_SHIELD_CHARGES_PER_LEVEL,
    ),
    Perk(
        id="gold_rush", name="Speedrunner",
        description="Bonus gold on a maze cleared under the par time.",
        effect_key="gold_rush", magnitude=GOLD_RUSH_BONUS_PER_LEVEL,
    ),
]

PERKS_BY_ID: dict[str, Perk] = {p.id: p for p in ALL_PERKS}
