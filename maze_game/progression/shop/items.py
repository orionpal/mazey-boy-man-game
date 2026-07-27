"""
items.py
--------
Active items (the other card type `shop/__init__.py::offer_shop_cards()`
draws from -- see `perks.py` for the passive counterpart), bound to fixed
Q/W/E/R slots, and the Loadout that tracks how many charges of each the
player has banked. Unlike perks, items have genuinely different mechanics
(breaking a wall, removing enemies, pausing the clock, nothing at all) --
there's no shared "effect_key" dispatch table like `perks.py`'s `EFFECTS`
here, because forcing four unrelated behaviours through one abstraction
wouldn't actually be simpler. Each item's effect is a dedicated method on
`LabyrinthRun` (`_try_break_wall`, `activate_laser`, `activate_stopwatch`,
`activate_squeaky_toy`); this module only holds the static definitions and
the charge-count bookkeeping shared by three of the four.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Item:
    id: str
    name: str
    description: str
    slot_key: str  # "Q" | "W" | "E" | "R" -- fixed 1:1 mapping, not dynamically assigned


ALL_ITEMS: list[Item] = [
    Item(
        id="wall_breaker", name="Wall Breaker", slot_key="Q",
        description="Hold + an arrow key: blast through the wall you'd hit (not a border wall). 1 charge.",
    ),
    Item(
        id="laser", name="Laser", slot_key="W",
        description="Fire lasers in all 4 directions from where you stand, destroying enemies hit. 1 charge.",
    ),
    Item(
        id="stopwatch", name="Stopwatch", slot_key="E",
        description="Stop time for a few seconds -- but you can't move either. 1 charge.",
    ),
    Item(
        id="squeaky_toy", name="Squeaky Toy", slot_key="R",
        description="Does nothing. Squeak!",
    ),
]

ITEMS_BY_ID: dict[str, Item] = {i.id: i for i in ALL_ITEMS}

# Squeaky Toy never gets a charge entry in Loadout.charges -- it has no
# limited resource, always usable once acquired.
UNLIMITED_ITEM_IDS = {"squeaky_toy"}


class Loadout:
    """The player's acquired items for this run -- reset on death (LabyrinthRun.restart())."""

    def __init__(self) -> None:
        self.charges: dict[str, int] = {}
        self.picks: dict[str, int] = {}

    def acquire(self, item: Item) -> None:
        self.picks[item.id] = self.picks.get(item.id, 0) + 1
        if item.id not in UNLIMITED_ITEM_IDS:
            self.charges[item.id] = self.charges.get(item.id, 0) + 1

    def consume_charge(self, item_id: str) -> bool:
        if self.charges.get(item_id, 0) <= 0:
            return False
        self.charges[item_id] -= 1
        return True
