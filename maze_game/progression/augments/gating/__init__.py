"""
augments/gating/
-----------------
Generation-time, mandatory-chain-capable augments: ones that do real work
in Augment.apply(), using the pocket-sealing/verification machinery in
_movement.py (pendant_subtree_map, seal_pocket, real_move_reachable) to
seal off part of the maze and force the player to interact with it. Split
out from augments/ once a third such augment (shifting_room.py) joined
teleporters.py/doors.py, pushing the flat file count over this project's
directory-size convention.

Re-exports the concrete Augment subclasses so augments/__init__.py's
registration step doesn't need to know about this split.
"""

from maze_game.progression.augments.gating.doors import DoorsAugment
from maze_game.progression.augments.gating.teleporters import TeleportersAugment

__all__ = ["DoorsAugment", "TeleportersAugment"]
