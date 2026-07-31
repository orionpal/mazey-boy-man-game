"""
meta/__init__.py
-----------------
Meta-progression: permanent upgrades bought with gold in the Base, between
runs (see progression/app.py::run_base()) -- distinct from the per-run
Perk shop (shop/perks.py), which resets to nothing on every death.
MetaProgress is the persistent half (loaded/saved to disk, mirrors
hazards.py's load_gold_total()/save_gold_total() shape exactly, right down
to reusing the same gold.json for the gold side of it); the Base class
(added alongside the renderer) is the ephemeral UI cursor state.

Deliberately reuses shop/perks.py's Build/EFFECTS machinery rather than
inventing a parallel one: an owned meta upgrade is just applied to a fresh
Build before the run starts (MetaProgress.seed_build()), through the exact
same effect_key -> multiplier-stacking functions Build.acquire() already
uses for in-run perk picks. The two compound naturally with no extra code.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from maze_game.constants import (
    META_PELLET_VALUE_MAGNITUDE, META_HAZARD_RESISTANCE_MAGNITUDE,
    META_UPGRADE_COST_BASE, META_UPGRADE_COST_STEP, APP_ROOT,
)
from maze_game.progression.entities.hazards import DEFAULT_GOLD_PATH, load_gold_total, save_gold_total
from maze_game.progression.shop.perks import Build, EFFECTS

DEFAULT_META_UPGRADES_PATH = APP_ROOT / "meta_upgrades.json"


@dataclass(frozen=True)
class MetaUpgrade:
    id: str
    name: str
    description: str
    effect_key: str
    magnitude: float
    cost_base: int
    cost_step: int


ALL_META_UPGRADES: list[MetaUpgrade] = [
    MetaUpgrade(
        id="pellet_bonus", name="Prospector's Eye",
        description="+10% time gained per pellet, permanently.",
        effect_key="pellet_value", magnitude=META_PELLET_VALUE_MAGNITUDE,
        cost_base=META_UPGRADE_COST_BASE, cost_step=META_UPGRADE_COST_STEP,
    ),
    MetaUpgrade(
        id="hazard_resistance", name="Thick Skin",
        description="-10% time lost to hazard contact, permanently.",
        effect_key="hazard_resistance", magnitude=META_HAZARD_RESISTANCE_MAGNITUDE,
        cost_base=META_UPGRADE_COST_BASE, cost_step=META_UPGRADE_COST_STEP,
    ),
]

META_UPGRADES_BY_ID: dict[str, MetaUpgrade] = {u.id: u for u in ALL_META_UPGRADES}


def load_meta_upgrade_levels(path: Path = DEFAULT_META_UPGRADES_PATH) -> dict[str, int]:
    """Load owned upgrade levels from disk. Returns {} if the file is missing, unreadable, or malformed."""
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return {}
    levels: dict[str, int] = {}
    if not isinstance(raw, dict):
        return {}
    for upgrade_id, level in raw.items():
        try:
            levels[upgrade_id] = int(level)
        except (TypeError, ValueError):
            continue  # skip malformed entries rather than fail the whole load
    return levels


def save_meta_upgrade_levels(levels: dict[str, int], path: Path = DEFAULT_META_UPGRADES_PATH) -> None:
    path.write_text(json.dumps(levels))


class MetaProgress:
    """
    Persistent meta-progression state: the player's gold balance (shared
    with, not owned by, this class -- gold.json's authoritative
    load/save lives in hazards.py) and owned upgrade levels. Constructed
    fresh each time the Base is shown, so it always reflects whatever gold
    the just-finished run left behind.
    """

    def __init__(self, gold_path: Path | None = None, upgrades_path: Path | None = None) -> None:
        # DEFAULT_GOLD_PATH/DEFAULT_META_UPGRADES_PATH are looked up here
        # (not as the parameters' default values, which bind at def-time
        # and would be immune to monkeypatching) so tests can isolate every
        # bare MetaProgress() call from the real on-disk files -- the exact
        # same reason LabyrinthRun.__init__ handles gold_path this way.
        self.gold_path = gold_path if gold_path is not None else DEFAULT_GOLD_PATH
        self.upgrades_path = upgrades_path if upgrades_path is not None else DEFAULT_META_UPGRADES_PATH
        self.gold = load_gold_total(self.gold_path)
        self.levels: dict[str, int] = load_meta_upgrade_levels(self.upgrades_path)

    def level_of(self, upgrade: MetaUpgrade) -> int:
        return self.levels.get(upgrade.id, 0)

    def cost_for(self, upgrade: MetaUpgrade) -> int:
        """Gold cost of the *next* purchase -- rises linearly with the level already owned."""
        return upgrade.cost_base + upgrade.cost_step * self.level_of(upgrade)

    def can_afford(self, upgrade: MetaUpgrade) -> bool:
        return self.gold >= self.cost_for(upgrade)

    def purchase(self, upgrade: MetaUpgrade) -> bool:
        """Deduct gold and level the upgrade up, persisting both. Returns False (no-op) if unaffordable."""
        cost = self.cost_for(upgrade)
        if self.gold < cost:
            return False
        self.gold -= cost
        self.levels[upgrade.id] = self.level_of(upgrade) + 1
        save_gold_total(self.gold, self.gold_path)
        save_meta_upgrade_levels(self.levels, self.upgrades_path)
        return True

    def seed_build(self) -> Build:
        """A fresh Build with every owned meta upgrade already applied -- the starting point for a new run."""
        build = Build()
        for upgrade in ALL_META_UPGRADES:
            effect = EFFECTS[upgrade.effect_key]
            for _ in range(self.level_of(upgrade)):
                effect(build, upgrade.magnitude)
        return build


class Base:
    """
    Cursor state for the Base screen -- one slot per upgrade tile, plus a
    final "Start Run" slot. Same shape as menu/__init__.py::MainMenu, for
    keyboard nav (arrows + space/enter) alongside mouse click.
    """

    def __init__(self) -> None:
        self.cursor = 0

    @property
    def slot_count(self) -> int:
        return len(ALL_META_UPGRADES) + 1

    def move_cursor(self, delta: int) -> None:
        self.cursor = (self.cursor + delta) % self.slot_count

    @property
    def on_start_run(self) -> bool:
        return self.cursor == len(ALL_META_UPGRADES)
