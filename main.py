"""
main.py
-------
Single entry point: opens to a main menu choosing between two modes.

- **Labyrinth Run**: the timed progression mode -- 100 mazes, gradually
  increasing in size, with one persistent time resource carried across the
  whole run (topped up by pellets, drained by enemies). Always launched
  from the Base (progression/app.py::run_progression_mode()), where
  persistent gold buys permanent meta-progression upgrades between runs;
  R after a run ends returns there instead of restarting in place. See
  docs/progression.md for the design decisions behind the starting numbers.
- **Relax (Free Play)**: a single maze at a time, adjustable size, no timer
  -- for practicing, or just wandering without pressure. Also runnable
  directly via mvp_main.py.

ESC backs out one level (in a game/the Base -> back to this menu; at the
menu -> quit); closing the window quits immediately from anywhere.

Run with:
    python main.py
"""

import pygame
from pygame._sdl2.video import Window

from maze_game.constants import FPS
from maze_game.media import sound
from maze_game.menu import MainMenu
from maze_game.menu.renderer import MenuRenderer
from maze_game.progression.app import run_progression_mode
from maze_game.freeplay.app import run_freeplay


def _sync_window_size(window: Window, size: tuple[int, int]) -> pygame.Surface:
    """Same in-place-resize approach used by both game-mode loops -- see freeplay/app.py's docstring for why."""
    if window.size != size:
        window.size = size
    return pygame.display.get_surface()


def run_menu(window: Window, clock: pygame.time.Clock) -> str | None:
    """Show the menu until a mode is chosen ("labyrinth"/"relax") or the player quits (None)."""
    menu = MainMenu()
    renderer = MenuRenderer(_sync_window_size(window, MenuRenderer.window_size()))

    while True:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                return None
            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    return None
                elif event.key in (pygame.K_UP, pygame.K_LEFT):
                    menu.move_cursor(-1)
                    sound.play("menu_move")
                elif event.key in (pygame.K_DOWN, pygame.K_RIGHT):
                    menu.move_cursor(1)
                    sound.play("menu_move")
                elif event.key in (pygame.K_RETURN, pygame.K_SPACE):
                    sound.play("menu_select")
                    return menu.selected_mode
            elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                for index, rect in enumerate(renderer.option_rects()):
                    if rect.collidepoint(event.pos):
                        menu.cursor = index
                        sound.play("menu_select")
                        return menu.selected_mode

        renderer.draw(menu, pygame.mouse.get_pos())
        pygame.display.flip()
        clock.tick(FPS)


def main() -> None:
    pygame.init()
    pygame.display.set_caption("Maze")
    clock = pygame.time.Clock()
    pygame.display.set_mode((1, 1))  # placeholder -- run_menu resizes it before the first frame draws
    window = Window.from_display_module()

    mode = run_menu(window, clock)
    while mode is not None:
        result = run_progression_mode(window, clock) if mode == "labyrinth" else run_freeplay(window, clock)
        if result == "quit":
            break
        mode = run_menu(window, clock)

    pygame.quit()


if __name__ == "__main__":
    main()
