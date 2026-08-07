"""
main.py
-------
Single entry point: opens to a main menu choosing between two modes.

- **Labyrinth Run**: the timed progression mode -- 100 mazes, gradually
  increasing in size, with one persistent time resource carried across the
  whole run (topped up by pellets, drained by hazards). Always launched
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

Also the pygbag entry point for the web build (see docs/web-build.md): pygbag
requires an async main loop -- the browser's single-threaded event loop can't
block on a plain `while` loop -- so every frame-driving loop here and in
progression/app.py/freeplay/app.py is `async def` with an `await
asyncio.sleep(0)` each frame to yield control back to it. Desktop behaviour
(asyncio.run(main()) on a normal CPython event loop) is unchanged either way.
"""

import asyncio
from typing import TYPE_CHECKING

import pygame

from maze_game.constants import FPS, IS_WEB
from maze_game.media import sound
from maze_game.menu import MainMenu
from maze_game.menu.renderer import MenuRenderer
from maze_game.progression.app import run_progression_mode
from maze_game.freeplay.app import run_freeplay

if TYPE_CHECKING:
    from pygame._sdl2.video import Window

_web_display_size: tuple[int, int] | None = None  # last size passed to set_mode() on web


def _sync_window_size(window: "Window | None", size: tuple[int, int]) -> pygame.Surface:
    """
    Same in-place-resize approach used by both game-mode loops -- see
    freeplay/app.py's docstring for why. `window` is None on web (IS_WEB):
    there's no native OS window to resize in place there, just the single
    canvas element, so pygame.display.set_mode() again is the right call --
    it's only flicker-prone tearing down/rebuilding a *native* window, which
    doesn't apply to a canvas.

    Still only called when `size` actually changes (mirrors the `window.size
    != size` guard below): calling set_mode() every frame regardless fights
    the browser's own live canvas/CSS layout during an actual window resize
    (e.g. OS window snap), which is what caused the reported squishing --
    each frame re-created the display mid-transition instead of settling on
    the final size once.
    """
    global _web_display_size
    if window is None:
        if _web_display_size != size:
            _web_display_size = size
            return pygame.display.set_mode(size)
        return pygame.display.get_surface()
    if window.size != size:
        window.size = size
    return pygame.display.get_surface()


async def run_menu(window: "Window | None", clock: pygame.time.Clock) -> str | None:
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
        await asyncio.sleep(0)


async def main() -> None:
    pygame.init()
    pygame.display.set_caption("Maze")
    clock = pygame.time.Clock()
    pygame.display.set_mode((1, 1))  # placeholder -- run_menu resizes it before the first frame draws

    window = None
    if not IS_WEB:
        from pygame._sdl2.video import Window
        window = Window.from_display_module()

    mode = await run_menu(window, clock)
    while mode is not None:
        result = await (run_progression_mode(window, clock) if mode == "labyrinth" else run_freeplay(window, clock))
        if result == "quit":
            break
        mode = await run_menu(window, clock)

    pygame.quit()


if __name__ == "__main__":
    asyncio.run(main())
