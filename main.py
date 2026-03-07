"""
main.py
-------
Entry point.  Initialises pygame, runs the event loop, and hands off
rendering / logic to the appropriate modules.

Run with:
    python main.py
"""

import pygame

from maze_game.constants import WIDTH, HEIGHT, FPS
from maze_game.game import Game
from maze_game.renderer import Renderer

# Arrow-key → direction vector mapping.
DIRECTION_MAP: dict[int, tuple[int, int]] = {
    pygame.K_UP:    ( 0, -1),
    pygame.K_DOWN:  ( 0,  1),
    pygame.K_LEFT:  (-1,  0),
    pygame.K_RIGHT: ( 1,  0),
}


def main() -> None:
    pygame.init()
    screen   = pygame.display.set_mode((WIDTH, HEIGHT))
    pygame.display.set_caption("Maze")
    clock    = pygame.time.Clock()

    game     = Game()
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

        # ── Update & draw ─────────────────────────────────────────────────
        game.update()
        renderer.draw(
            grid      = game.grid,
            player    = game.player,
            goal      = game.goal,
            elapsed   = game.elapsed,
            best_time = game.best_time,
            finished  = game.finished,
        )
        pygame.display.flip()
        clock.tick(FPS)

    pygame.quit()


if __name__ == "__main__":
    main()
