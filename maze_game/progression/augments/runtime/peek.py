"""
peek.py
-------
Makes the pause menu's black overlay (see progression/app.py::_run_pause_loop()
and progression/renderer.py::Renderer.draw_pause_overlay()) start
transparent and fade to fully opaque over PEEK_FADE_DURATION_SECONDS,
instead of snapping opaque the instant the player pauses -- gives a short
window to actually study the maze (plan a route) before it's hidden again.
Restarts fresh every time the pause menu opens (see peek_alpha()'s
docstring).

Purely a runtime/rendering effect: apply() is a no-op (nothing to do at
generation time), same shape as fog.py/rotation.py -- _run_pause_loop()
reads augment_build.level_of("peek") directly at runtime instead.
"""

from __future__ import annotations

from maze_game.constants import PEEK_FADE_DURATION_SECONDS
from maze_game.progression.augments import Augment, AugmentContext


class PeekAugment(Augment):
    id = "peek"
    name = "Peek"
    description = "Pausing doesn't instantly black out the maze -- you get a few seconds to study it before it fades to black."

    def apply(self, ctx: AugmentContext) -> None:
        pass  # runtime-only effect -- see this module's docstring


def peek_alpha(elapsed: float) -> int:
    """
    Overlay alpha (0 = fully transparent, 255 = fully opaque) `elapsed`
    seconds into a pause, ramping linearly over PEEK_FADE_DURATION_SECONDS
    and clamped at the ends. A pure function of elapsed time (not tied to
    any persistent LabyrinthRun/Build state) -- _run_pause_loop() computes
    `elapsed` from when *that specific pause* began, so the fade always
    restarts fresh on the next ESC press rather than carrying over.
    """
    progress = max(0.0, min(1.0, elapsed / PEEK_FADE_DURATION_SECONDS))
    return round(255 * progress)
