"""
app.py
------
The free-play event loop, factored out of mvp_main.py so it can be reused
both by that standalone entry point and by main.py's "Relax" menu option
without duplicating the loop.
"""

import pygame
from pygame._sdl2.video import Window

from maze_game.constants import FPS
from maze_game.freeplay.game import Game
from maze_game.freeplay.renderer import Renderer, Layout

DIRECTION_MAP: dict[int, tuple[int, int]] = {
    pygame.K_UP:    ( 0, -1),
    pygame.K_DOWN:  ( 0,  1),
    pygame.K_LEFT:  (-1,  0),
    pygame.K_RIGHT: ( 1,  0),
}


def sync_window_size(window: Window, size: tuple[int, int]) -> pygame.Surface:
    """
    Resize the existing native window in place to `size`. Deliberately uses
    Window.size instead of calling pygame.display.set_mode() again --
    re-calling set_mode() with a different size tears down the old native
    window and creates a brand new one (confirmed via
    pygame.display.get_wm_info()['window'] changing), which is what made
    resizing look like the whole game window closing and reopening. Setting
    .size on the already-created Window resizes it in place (same window
    ID), and is a cheap no-op when the size is unchanged.
    """
    if window.size != size:
        window.size = size
    return pygame.display.get_surface()


def run_freeplay(window: Window, clock: pygame.time.Clock) -> str:
    """
    Play free-play mode until the player quits. Returns "quit" if the
    window was closed (the whole app should exit) or "menu" if ESC/Q was
    pressed (a standalone launch treats this the same as "quit"; main.py's
    menu-driven launch returns to the menu instead).
    """
    game = Game()
    renderer = Renderer(sync_window_size(window, Renderer.window_size(game.cols, game.rows, len(game.history))))

    while True:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                return "quit"

            elif event.type == pygame.KEYDOWN:
                if event.key in (pygame.K_ESCAPE, pygame.K_q):
                    return "menu"
                elif event.key == pygame.K_r:
                    game.new_maze()
                elif event.key in DIRECTION_MAP:
                    game.move(DIRECTION_MAP[event.key])

            elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                layout = Layout(game.cols, game.rows, len(game.history))
                if layout.cols_minus.collidepoint(event.pos):
                    game.adjust_cols(-1)
                elif layout.cols_plus.collidepoint(event.pos):
                    game.adjust_cols(1)
                elif layout.rows_minus.collidepoint(event.pos):
                    game.adjust_rows(-1)
                elif layout.rows_plus.collidepoint(event.pos):
                    game.adjust_rows(1)

        game.update()
        renderer.set_surface(sync_window_size(window, Renderer.window_size(game.cols, game.rows, len(game.history))))
        renderer.draw(
            grid      = game.grid,
            player    = game.player,
            goal      = game.goal,
            elapsed   = game.elapsed,
            best_time = game.best_time,
            finished  = game.finished,
            cols      = game.cols,
            rows      = game.rows,
            history   = game.history,
        )
        pygame.display.flip()
        clock.tick(FPS)
