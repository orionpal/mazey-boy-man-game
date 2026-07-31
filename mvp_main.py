"""
mvp_main.py
-----------
Entry point for free-play mode on its own: a single maze at a time,
adjustable size via the sidebar, no time limit. The actual event loop lives
in maze_game/freeplay/app.py::run_freeplay() -- this script just bootstraps
pygame and a window for it, so main.py's "Relax" menu option can reuse the
exact same loop without duplicating it.

For the 100-maze labyrinth progression mode (gradually increasing size,
per-maze time limits, group breaks), see main.py instead -- it also opens
to a menu offering this mode.

Run with:
    python mvp_main.py
"""

import pygame
from pygame._sdl2.video import Window

from maze_game.freeplay.app import run_freeplay


def main() -> None:
    pygame.init()
    pygame.display.set_caption("Maze")
    clock = pygame.time.Clock()
    pygame.display.set_mode((1, 1))  # placeholder -- run_freeplay resizes it before the first frame draws
    window = Window.from_display_module()

    run_freeplay(window, clock)

    pygame.quit()


if __name__ == "__main__":
    main()
