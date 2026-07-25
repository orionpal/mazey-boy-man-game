"""
main.py
-------
Entry point.  Initialises pygame, runs the event loop, and hands off
rendering / logic to the appropriate modules.

Run with:
    python main.py
"""

import pygame

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


def resize_window(game: Game) -> pygame.Surface:
    """(Re)create the display surface to fit the current maze dimensions."""
    size = Renderer.window_size(game.cols, game.rows)
    return pygame.display.set_mode(size)


def main() -> None:
    pygame.init()
    pygame.display.set_caption("Maze")
    clock = pygame.time.Clock()

    game     = Game()
    screen   = resize_window(game)
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
                    screen = resize_window(game)
                    renderer.set_surface(screen)
                elif layout.cols_plus.collidepoint(event.pos):
                    game.adjust_cols(1)
                    screen = resize_window(game)
                    renderer.set_surface(screen)
                elif layout.rows_minus.collidepoint(event.pos):
                    game.adjust_rows(-1)
                    screen = resize_window(game)
                    renderer.set_surface(screen)
                elif layout.rows_plus.collidepoint(event.pos):
                    game.adjust_rows(1)
                    screen = resize_window(game)
                    renderer.set_surface(screen)

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
