"""
app.py
------
The labyrinth-run event loop, factored out of main.py so it can be reused
both by that entry point's menu and (if ever needed) elsewhere without
duplicating the loop.

Also the sound side of asset-readiness (see docs/assets.md): LabyrinthRun
reports what happened each frame via run.events (a plain list of event-name
strings, same idea as its add_popup() mechanism) rather than calling
pygame.mixer itself -- run.py stays a pure state machine, independent of
pygame. This loop drains and clears that list once per frame, playing
whatever sound (if any) exists for each event.
"""

import pygame
from pygame._sdl2.video import Window

from maze_game.constants import FPS
from maze_game.media import sound
from maze_game.progression.run import LabyrinthRun
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


def sync_window_size(window: Window, size: tuple[int, int]) -> pygame.Surface:
    """Same in-place-resize approach as freeplay/app.py -- see its docstring for why."""
    if window.size != size:
        window.size = size
    return pygame.display.get_surface()


def run_labyrinth(window: Window, clock: pygame.time.Clock) -> str:
    """
    Play a labyrinth run until the player backs out. Returns "quit" if the
    window was closed (the whole app should exit) or "menu" if ESC was
    pressed (back to main.py's menu -- a run in progress is simply
    abandoned, same as closing the game used to do).
    """
    run = LabyrinthRun()
    renderer = Renderer(sync_window_size(window, Renderer.window_size(run.cols, run.rows)))

    while True:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                return "quit"
            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    return "menu"
                elif event.key == pygame.K_r and (run.failed or run.completed_run):
                    run.restart()
                elif run.on_break:
                    if event.key in (pygame.K_LEFT, pygame.K_UP):
                        run.move_break_cursor(-1)
                    elif event.key in (pygame.K_RIGHT, pygame.K_DOWN):
                        run.move_break_cursor(1)
                    elif event.key == pygame.K_SPACE:
                        run.choose_break_card(run.break_cursor)
                    elif event.key in SHOP_CHOICE_KEYS:
                        run.choose_break_card(SHOP_CHOICE_KEYS[event.key])
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
                        run.choose_break_card(index)
                        break

        run.update()
        for event_name in run.events:
            sound.play(event_name)
        run.events.clear()

        renderer.set_surface(sync_window_size(window, Renderer.window_size(run.cols, run.rows)))
        renderer.draw(run)
        pygame.display.flip()
        clock.tick(FPS)
