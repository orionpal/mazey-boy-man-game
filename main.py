"""
main.py
-------
Entry point.  Initialises pygame, runs the event loop, and hands off
rendering / logic to the appropriate modules.

Run with:
    python main.py
"""

import pygame
from pygame._sdl2.video import Window

from maze_game.constants import FPS
from maze_game.game import Game
from maze_game.renderer import Renderer, Layout

# Arrow-key → direction vector mapping.
DIRECTION_MAP: dict[int, tuple[int, int]] = {
    pygame.K_UP:    ( 0, -1),
    pygame.K_DOWN:  ( 0,  1),
    pygame.K_LEFT:  (-1,  0),
    pygame.K_RIGHT: ( 1,  0),
}


def resize_window(window: Window, game: Game) -> pygame.Surface:
    """
    Resize the existing native window in place to fit the current maze
    dimensions, and return the (possibly new) display surface.

    Deliberately uses Window.size instead of calling pygame.display.set_mode()
    again -- re-calling set_mode() with a different size tears down the old
    native window and creates a brand new one (confirmed via
    pygame.display.get_wm_info()['window'] changing), which is what made
    resizing look like the whole game window closing and reopening. Setting
    .size on the already-created Window resizes it in place; the window ID
    stays the same.
    """
    size = Renderer.window_size(game.cols, game.rows)
    if window.size != size:
        window.size = size
    return pygame.display.get_surface()


def main() -> None:
    pygame.init()
    pygame.display.set_caption("Maze")
    clock = pygame.time.Clock()

    game     = Game()
    screen   = pygame.display.set_mode(Renderer.window_size(game.cols, game.rows))
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
                layout = Layout(game.cols, game.rows)
                if layout.cols_minus.collidepoint(event.pos):
                    game.adjust_cols(-1)
                    renderer.set_surface(resize_window(window, game))
                elif layout.cols_plus.collidepoint(event.pos):
                    game.adjust_cols(1)
                    renderer.set_surface(resize_window(window, game))
                elif layout.rows_minus.collidepoint(event.pos):
                    game.adjust_rows(-1)
                    renderer.set_surface(resize_window(window, game))
                elif layout.rows_plus.collidepoint(event.pos):
                    game.adjust_rows(1)
                    renderer.set_surface(resize_window(window, game))

        # ── Update & draw ─────────────────────────────────────────────────
        game.update()
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
