"""
perks.py
--------
Passive perks -- the shop break's card pool -- and the Build that
accumulates them. `magnitude` is added (not multiplied) on each pick:
both current perks grant a charge/bonus count (hazard contacts ignored,
gold awarded), not a rate, so stacking is additive.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from maze_game.constants import (
    HAZARD_SHIELD_CHARGES_PER_LEVEL, GOLD_RUSH_BONUS_PER_LEVEL,
    MOMENTUM_PELLET_VALUE_BONUS_PER_LEVEL, COMPOUND_INTEREST_RATE_PER_LEVEL, SECOND_WIND_CHARGES_PER_LEVEL,
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
        # progression/meta/'s "hazard resistance" upgrade, seeded onto a
        # fresh Build before the run starts (see MetaProgress.seed_build()).
        self.hazard_resistance_multiplier = 1.0
        # Bulwark: ignored hazard contacts, refilled to this count every maze
        # (see LabyrinthRun._begin_maze()'s shield_charges_remaining reset).
        self.hazard_shield_charges_per_maze = 0
        # Speedrunner: bonus gold awarded alongside the existing automatic
        # time bonus on an under-par maze clear.
        self.gold_rush_bonus = 0
        # Momentum: NOT read by acquire()'s own magnitude math like every
        # field above -- it's the per-clean-clear increment amount, applied
        # to pellet_value_multiplier from LabyrinthRun.update()'s
        # maze-cleared branch on a gameplay event (a hazard-free clear),
        # not from here.
        self.momentum_bonus_per_clear = 0.0
        # Compound Interest: seconds of time granted per held gold per
        # second, applied continuously from LabyrinthRun.update() (not tied
        # to any single event like a pellet pickup).
        self.compound_interest_rate = 0.0
        # Second Wind: extra "the time resource hitting 0 doesn't actually
        # fail the run" charges for this run, consumed in
        # LabyrinthRun.update()'s depletion check.
        self.second_wind_charges = 0

    def acquire(self, perk: Perk) -> None:
        self.picks[perk.id] = self.picks.get(perk.id, 0) + 1
        EFFECTS[perk.effect_key](self, perk.magnitude)


def _apply_pellet_frequency(build: Build, magnitude: float) -> None:
    build.pellet_frequency_multiplier *= magnitude


def _apply_pellet_value(build: Build, magnitude: float) -> None:
    build.pellet_value_multiplier *= magnitude


def _apply_hazard_resistance(build: Build, magnitude: float) -> None:
    build.hazard_resistance_multiplier *= magnitude


def _apply_hazard_shield(build: Build, magnitude: float) -> None:
    build.hazard_shield_charges_per_maze += int(magnitude)


def _apply_gold_rush(build: Build, magnitude: float) -> None:
    build.gold_rush_bonus += int(magnitude)


def _apply_momentum(build: Build, magnitude: float) -> None:
    build.momentum_bonus_per_clear += magnitude


def _apply_compound_interest(build: Build, magnitude: float) -> None:
    build.compound_interest_rate += magnitude


def _apply_second_wind(build: Build, magnitude: float) -> None:
    build.second_wind_charges += int(magnitude)


EFFECTS: dict[str, Callable[[Build, float], None]] = {
    "pellet_frequency": _apply_pellet_frequency,
    "pellet_value": _apply_pellet_value,
    "hazard_resistance": _apply_hazard_resistance,
    "hazard_shield": _apply_hazard_shield,
    "gold_rush": _apply_gold_rush,
    "momentum": _apply_momentum,
    "compound_interest": _apply_compound_interest,
    "second_wind": _apply_second_wind,
}

ALL_PERKS: list[Perk] = [
    Perk(
        id="hazard_shield", name="Bulwark",
        description="Ignore the first hazard contact each maze.",
        effect_key="hazard_shield", magnitude=HAZARD_SHIELD_CHARGES_PER_LEVEL,
    ),
    Perk(
        id="gold_rush", name="Speedrunner",
        description="Bonus gold on a maze cleared under the par time.",
        effect_key="gold_rush", magnitude=GOLD_RUSH_BONUS_PER_LEVEL,
    ),
    Perk(
        id="momentum", name="Momentum",
        description="Clearing a maze with zero hazard contacts permanently boosts pellet value for the rest of this run.",
        effect_key="momentum", magnitude=MOMENTUM_PELLET_VALUE_BONUS_PER_LEVEL,
    ),
    Perk(
        id="compound_interest", name="Compound Interest",
        description="Held gold passively grants a trickle of time.",
        effect_key="compound_interest", magnitude=COMPOUND_INTEREST_RATE_PER_LEVEL,
    ),
    Perk(
        id="second_wind", name="Second Wind",
        description="Running out of time doesn't end the run -- refills a little time instead, once per run.",
        effect_key="second_wind", magnitude=SECOND_WIND_CHARGES_PER_LEVEL,
    ),
]

PERKS_BY_ID: dict[str, Perk] = {p.id: p for p in ALL_PERKS}
