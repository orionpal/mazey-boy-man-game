"""
app.py
------
The arena interlude's pygame event loop, mirroring the shape of
progression/app.py::run_labyrinth() (event pump -> state.update() ->
renderer.draw() -> clock.tick). progression/app.py calls run_arena() when
a LabyrinthRun raises the one-time ``"arena"`` break, then banks the
returned state's treasure gold via run.finish_arena().

Controls: arrows or WASD -- left/right turn 90 deg in place, up/down move
one cell. SPACE strikes a blocker directly ahead. ESC leaves early.
"""

from __future__ import annotations

import random

import pygame
from pygame._sdl2.video import Window

from maze_game.constants import (
    FPS, ARENA_TIME_BUDGET, ARENA_START_HEALTH, ARENA_ENEMY_COUNT,
    ARENA_TREASURE_COUNT, ARENA_TREASURE_GOLD,
)
from maze_game.presentation.media import sound
from maze_game.progression.run import FirstMazeRecord
from maze_game.arena.state import ArenaState
from maze_game.arena.renderer import ArenaRenderer

_TURN_LEFT = (pygame.K_LEFT, pygame.K_a)
_TURN_RIGHT = (pygame.K_RIGHT, pygame.K_d)
_FORWARD = (pygame.K_UP, pygame.K_w)
_BACK = (pygame.K_DOWN, pygame.K_s)


def _sync_window_size(window: Window, size: tuple[int, int]) -> pygame.Surface:
    """Same in-place-resize approach as the other mode loops -- see freeplay/app.py."""
    if window.size != size:
        window.size = size
    return pygame.display.get_surface()


def run_arena(
    window: Window,
    clock: pygame.time.Clock,
    record: FirstMazeRecord,
    rng: random.Random,
) -> ArenaState:
    """
    Play the 3D replay of `record` until it resolves (win / lose / timeout)
    or the player leaves (ESC / window close -> outcome "quit"). Returns the
    final ArenaState; the caller reads `.gold_collected` off it.
    """
    state = ArenaState(
        record=record,
        rng=rng,
        time_budget=ARENA_TIME_BUDGET,
        max_health=ARENA_START_HEALTH,
        enemy_count=ARENA_ENEMY_COUNT,
        treasure_count=ARENA_TREASURE_COUNT,
        treasure_gold=ARENA_TREASURE_GOLD,
    )
    renderer = ArenaRenderer(_sync_window_size(window, ArenaRenderer.window_size()))

    while True:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                if not state.over:
                    state.outcome = "quit"
                return state
            if event.type != pygame.KEYDOWN:
                continue
            if state.over:
                return state  # any key dismisses the result screen
            if event.key == pygame.K_ESCAPE:
                state.outcome = "quit"
                return state
            if event.key in _TURN_LEFT:
                state.turn(-1)
            elif event.key in _TURN_RIGHT:
                state.turn(1)
            elif event.key in _FORWARD:
                state.step(1)
            elif event.key in _BACK:
                state.step(-1)
            elif event.key == pygame.K_SPACE:
                state.attack()

        state.update()
        for event_name in state.events:
            sound.play(event_name)
        state.events.clear()

        renderer.set_surface(_sync_window_size(window, ArenaRenderer.window_size()))
        renderer.draw(state)
        pygame.display.flip()
        clock.tick(FPS)
