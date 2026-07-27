"""
mvp_main.py
-----------
Entry point for free-play mode: a single maze at a time, adjustable size
via the sidebar, no time limit. Initialises pygame, runs the event loop,
and hands off rendering / logic to the appropriate modules.

For the 100-maze labyrinth progression mode (gradually increasing size,
per-maze time limits, group breaks), see main.py instead.

Run with:
    python mvp_main.py
"""

import pygame
from pygame._sdl2.video import Window

from maze_game.constants import FPS
from maze_game.freeplay.game import Game
from maze_game.freeplay.renderer import Renderer, Layout

# Arrow-key → direction vector mapping.
DIRECTION_MAP: dict[int, tuple[int, int]] = {
    pygame.K_UP:    ( 0, -1),
    pygame.K_DOWN:  ( 0,  1),
    pygame.K_LEFT:  (-1,  0),
    pygame.K_RIGHT: ( 1,  0),
}


def sync_window_size(window: Window, game: Game) -> pygame.Surface:
    """
    Resize the existing native window in place to fit whatever the current
    content needs (maze size AND history-list length -- a small maze with
    enough history entries needs a taller window than the maze alone would,
    otherwise history text overflows past the window edge into the HUD).

    Called every frame; deliberately uses Window.size instead of calling
    pygame.display.set_mode() again -- re-calling set_mode() with a
    different size tears down the old native window and creates a brand new
    one (confirmed via pygame.display.get_wm_info()['window'] changing),
    which is what made resizing look like the whole game window closing and
    reopening. Setting .size on the already-created Window resizes it in
    place (same window ID), and is a cheap no-op when the size is unchanged.
    """
    size = Renderer.window_size(game.cols, game.rows, len(game.history))
    if window.size != size:
        window.size = size
    return pygame.display.get_surface()


def main() -> None:
    pygame.init()
    pygame.display.set_caption("Maze")
    clock = pygame.time.Clock()

    game     = Game()
    screen   = pygame.display.set_mode(Renderer.window_size(game.cols, game.rows, len(game.history)))
    window   = Window.from_display_module()
    renderer = Renderer(screen)

    running = True
    while running:
        # ── Events ────────────────────────────────────────────────────────
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False

            elif event.type == pygame.KEYDOWN:
                if event.key in (pygame.K_ESCAPE, pygame.K_q):
                    running = False
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

        # ── Update & draw ─────────────────────────────────────────────────
        game.update()
        renderer.set_surface(sync_window_size(window, game))
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

    pygame.quit()


if __name__ == "__main__":
    main()
