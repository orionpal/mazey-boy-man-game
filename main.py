"""
main.py
-------
Entry point: the labyrinth progression mode. 100 mazes, gradually
increasing in size, with one persistent time resource carried across the
whole run (topped up by pellets, drained by enemies/the boss). Groups of 5
mazes stitch together seamlessly; a shop-card choice (a passive perk or an
active Q/W/E/R item) follows each group. Running out of time ends the whole
run back at maze 1.

See docs/progression.md for the design decisions behind the starting
numbers (dimensions ramp, time economy, fail behaviour) -- this is a first
guess meant to be played and retuned, not a final balance pass.

For the original single-maze, no-time-limit, adjustable-size free-play mode,
see mvp_main.py instead.

Run with:
    python main.py
"""

import pygame
from pygame._sdl2.video import Window

from maze_game.constants import FPS
from maze_game.progression import LabyrinthRun
from maze_game.progression.renderer import Renderer, Layout

DIRECTION_MAP: dict[int, tuple[int, int]] = {
    pygame.K_UP:    ( 0, -1),
    pygame.K_DOWN:  ( 0,  1),
    pygame.K_LEFT:  (-1,  0),
    pygame.K_RIGHT: ( 1,  0),
}

SHOP_CHOICE_KEYS: dict[int, int] = {
    pygame.K_1: 0,
    pygame.K_2: 1,
    pygame.K_3: 2,
}


def _junction_stop_count(keys_held) -> int | None:
    """Hold SPACE + an arrow key: run to the next wall, ignoring intersections. Otherwise, a normal single-press move."""
    return None if keys_held[pygame.K_SPACE] else 1


def sync_window_size(window: Window, run: LabyrinthRun) -> pygame.Surface:
    """Same in-place-resize approach as mvp_main.py -- see its docstring for why."""
    size = Renderer.window_size(run.cols, run.rows)
    if window.size != size:
        window.size = size
    return pygame.display.get_surface()


def main() -> None:
    pygame.init()
    pygame.display.set_caption("Maze -- Labyrinth")
    clock = pygame.time.Clock()

    run = LabyrinthRun()
    screen = pygame.display.set_mode(Renderer.window_size(run.cols, run.rows))
    window = Window.from_display_module()
    renderer = Renderer(screen)

    running = True
    while running:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    running = False
                elif event.key == pygame.K_r and (run.failed or run.completed_run):
                    run.restart()
                elif run.on_break:
                    if event.key in (pygame.K_LEFT, pygame.K_UP):
                        run.move_shop_cursor(-1)
                    elif event.key in (pygame.K_RIGHT, pygame.K_DOWN):
                        run.move_shop_cursor(1)
                    elif event.key == pygame.K_SPACE:
                        run.choose_shop_card(run.shop_cursor)
                    elif event.key in SHOP_CHOICE_KEYS:
                        run.choose_shop_card(SHOP_CHOICE_KEYS[event.key])
                elif event.key == pygame.K_w:
                    run.activate_laser()
                elif event.key == pygame.K_e:
                    run.activate_stopwatch()
                elif event.key == pygame.K_r:
                    run.activate_squeaky_toy()
                elif event.key in DIRECTION_MAP:
                    keys_held = pygame.key.get_pressed()
                    if keys_held[pygame.K_q]:
                        run.move(DIRECTION_MAP[event.key], use_wall_breaker=True)
                    else:
                        run.move(DIRECTION_MAP[event.key], _junction_stop_count(keys_held))
            elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1 and run.on_break:
                layout = Layout(run.cols, run.rows)
                for index, card in enumerate(layout.cards):
                    if card.collidepoint(event.pos):
                        run.choose_shop_card(index)
                        break

        run.update()
        renderer.set_surface(sync_window_size(window, run))
        renderer.draw(run)
        pygame.display.flip()
        clock.tick(FPS)

    pygame.quit()


if __name__ == "__main__":
    main()
