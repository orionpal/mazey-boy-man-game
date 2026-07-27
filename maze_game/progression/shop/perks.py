"""
perks.py
--------
Passive perks (one of the two card types `shop/__init__.py::offer_shop_cards()`
draws from -- see `items.py` for the active-item counterpart) and the Build
that accumulates them. Stacking is deliberately multiplicative/compounding --
picking the same perk again multiplies its multiplier by `magnitude` again
-- since there are only 3 placeholder perks and repeat picks are common
across a run, not an edge case, and this needed a pinned-down rule rather
than being left implicit.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from maze_game.constants import (
    PELLET_FREQUENCY_PERK_MAGNITUDE, PELLET_VALUE_PERK_MAGNITUDE, STRENGTH_PERK_MAGNITUDE,
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
        self.pellet_frequency_multiplier = 1.0
        self.pellet_value_multiplier = 1.0
        self.strength_multiplier = 1.0

    def acquire(self, perk: Perk) -> None:
        self.picks[perk.id] = self.picks.get(perk.id, 0) + 1
        EFFECTS[perk.effect_key](self, perk.magnitude)


def _apply_pellet_frequency(build: Build, magnitude: float) -> None:
    build.pellet_frequency_multiplier *= magnitude


def _apply_pellet_value(build: Build, magnitude: float) -> None:
    build.pellet_value_multiplier *= magnitude


def _apply_strength(build: Build, magnitude: float) -> None:
    build.strength_multiplier *= magnitude


EFFECTS: dict[str, Callable[[Build, float], None]] = {
    "pellet_frequency": _apply_pellet_frequency,
    "pellet_value": _apply_pellet_value,
    "strength": _apply_strength,
}

ALL_PERKS: list[Perk] = [
    Perk(
        id="pellet_frequency", name="Keen Eye",
        description="+20% pellet spawn frequency in future mazes.",
        effect_key="pellet_frequency", magnitude=PELLET_FREQUENCY_PERK_MAGNITUDE,
    ),
    Perk(
        id="pellet_value", name="Rich Vein",
        description="+30% time gained per pellet.",
        effect_key="pellet_value", magnitude=PELLET_VALUE_PERK_MAGNITUDE,
    ),
    Perk(
        id="strength", name="Iron Fist",
        description="+50% damage dealt to bosses.",
        effect_key="strength", magnitude=STRENGTH_PERK_MAGNITUDE,
    ),
]

PERKS_BY_ID: dict[str, Perk] = {p.id: p for p in ALL_PERKS}
