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

import asyncio
import time
from typing import TYPE_CHECKING

import pygame

from maze_game.constants import FPS
from maze_game.media import sound
from maze_game.progression.run import LabyrinthRun, PauseMenu, PEEK_ID
from maze_game.progression.renderer import Renderer, Layout
from maze_game.progression.meta import Base, MetaProgress, ALL_META_UPGRADES
from maze_game.progression.meta.renderer import BaseRenderer
from maze_game.progression.augments.runtime.peek import peek_alpha

if TYPE_CHECKING:
    from pygame._sdl2.video import Window

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


_web_display_size: tuple[int, int] | None = None  # last size passed to set_mode() on web


def sync_window_size(window: "Window | None", size: tuple[int, int]) -> pygame.Surface:
    """
    Same in-place-resize approach as freeplay/app.py -- see its docstring for
    why. `window` is None on web. Only calls set_mode() when `size` actually
    changes -- see main.py's _sync_window_size() for why that matters on web.
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


async def _run_pause_loop(window: "Window | None", clock: pygame.time.Clock, run: LabyrinthRun, renderer: Renderer) -> str:
    """
    Shows the pause menu until the player picks "Resume"/"Return to Base",
    or closes the window. Returns "quit" / "resumed" / "base" -- exactly
    PauseMenu's own result strings, see run.py::PAUSE_OPTIONS.

    Opaque black the instant this loop starts, by default -- unless the
    Peek augment is active, in which case the overlay starts transparent
    and fades to opaque over PEEK_FADE_DURATION_SECONDS (see
    augments/runtime/peek.py::peek_alpha()). `pause_started_at` is a fresh
    local every call, so the fade window restarts on every ESC press
    rather than carrying over from a previous pause.

    Deliberately its own nested loop (mirrors main.py::run_menu()'s shape
    exactly) rather than folding pause handling into run_labyrinth()'s own
    loop -- run.update() is simply never called while this loop owns
    control, so the maze stays genuinely frozen (same idea as on_break
    already not calling it) with no extra "are we paused" branching
    threaded through the normal frame body.
    """
    menu = PauseMenu()
    peek_active = run.augment_build.level_of(PEEK_ID) > 0
    pause_started_at = time.monotonic()
    while True:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                return "quit"
            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    return "resumed"
                elif event.key in (pygame.K_UP, pygame.K_LEFT):
                    menu.move_cursor(-1)
                    sound.play("menu_move")
                elif event.key in (pygame.K_DOWN, pygame.K_RIGHT):
                    menu.move_cursor(1)
                    sound.play("menu_move")
                elif event.key in (pygame.K_RETURN, pygame.K_SPACE):
                    sound.play("menu_select")
                    return menu.selected
            elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                for index, rect in enumerate(renderer.pause_option_rects()):
                    if rect.collidepoint(event.pos):
                        menu.cursor = index
                        sound.play("menu_select")
                        return menu.selected

        alpha = peek_alpha(time.monotonic() - pause_started_at) if peek_active else 255
        renderer.draw_pause_overlay(run, menu, pygame.mouse.get_pos(), alpha=alpha)
        pygame.display.flip()
        clock.tick(FPS)
        await asyncio.sleep(0)


async def run_labyrinth(window: "Window | None", clock: pygame.time.Clock) -> str:
    """
    Play a labyrinth run until it ends or the player backs out. Returns
    "quit" if the window was closed (the whole app should exit), or "base"
    if either R was pressed after a fail/complete screen, or the player
    chose "Return to Base" from the pause menu (see _run_pause_loop() --
    ESC now opens that instead of instantly abandoning the run the way it
    used to). Either "base" path routes back into run_base() via
    run_progression_mode() to spend gold before the next run, rather than
    restarting in place.
    """
    run = LabyrinthRun()
    renderer = Renderer(sync_window_size(window, Renderer.window_size(run.cols, run.rows)))

    while True:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                return "quit"
            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    result = await _run_pause_loop(window, clock, run, renderer)
                    # The pause loop never called run.time.tick()/rotation_timer.tick() --
                    # resync both before ticking resumes, or the entire paused
                    # stretch gets charged as elapsed time in one lump on the very
                    # next tick() (same staleness bug resync() exists to prevent for
                    # breaks -- see TimeResource.resync()'s docstring). Cheap even
                    # when `run` is about to be discarded (the "quit"/"base" cases).
                    run.time.resync()
                    run.rotation_timer.resync()
                    if result in ("quit", "base"):
                        return result
                    # "resumed" -- fall through, keep playing.
                elif event.key == pygame.K_r and (run.failed or run.completed_run):
                    return "base"
                elif run.on_break:
                    if event.key in (pygame.K_LEFT, pygame.K_UP):
                        run.move_break_cursor(-1)
                    elif event.key in (pygame.K_RIGHT, pygame.K_DOWN):
                        run.move_break_cursor(1)
                    elif event.key == pygame.K_SPACE:
                        run.choose_break_card(run.break_cursor)
                    elif event.key in SHOP_CHOICE_KEYS:
                        run.choose_break_card(SHOP_CHOICE_KEYS[event.key])
                elif event.key in DIRECTION_MAP:
                    keys_held = pygame.key.get_pressed()
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
        await asyncio.sleep(0)


def _try_purchase(progress: MetaProgress, upgrade) -> None:
    """Silent no-op if unaffordable -- no error sound/popup, it just doesn't happen."""
    if progress.purchase(upgrade):
        sound.play("card_select")  # reuses the existing "a choice was confirmed" event


async def run_base(window: "Window | None", clock: pygame.time.Clock) -> str:
    """
    Show the Base until the player starts a run or backs out. Returns
    "start" (launch a fresh run), "menu" (ESC, back to the title screen),
    or "quit" (window closed). A fresh MetaProgress is loaded on every
    call, so it always reflects whatever gold the just-finished run left
    behind.
    """
    progress = MetaProgress()
    base = Base()
    renderer = BaseRenderer(sync_window_size(window, BaseRenderer.window_size()))

    while True:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                return "quit"
            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    return "menu"
                elif event.key in (pygame.K_LEFT, pygame.K_UP):
                    base.move_cursor(-1)
                    sound.play("menu_move")
                elif event.key in (pygame.K_RIGHT, pygame.K_DOWN):
                    base.move_cursor(1)
                    sound.play("menu_move")
                elif event.key in (pygame.K_RETURN, pygame.K_SPACE):
                    if base.on_start_run:
                        sound.play("menu_select")
                        return "start"
                    _try_purchase(progress, ALL_META_UPGRADES[base.cursor])
                elif event.key in SHOP_CHOICE_KEYS:
                    index = SHOP_CHOICE_KEYS[event.key]
                    if index < len(ALL_META_UPGRADES):
                        base.cursor = index
                        _try_purchase(progress, ALL_META_UPGRADES[index])
            elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                clicked_tile = False
                for index, rect in enumerate(renderer.tile_rects()):
                    if rect.collidepoint(event.pos):
                        base.cursor = index
                        _try_purchase(progress, ALL_META_UPGRADES[index])
                        clicked_tile = True
                        break
                if not clicked_tile and renderer.start_button_rect().collidepoint(event.pos):
                    base.cursor = len(ALL_META_UPGRADES)
                    sound.play("menu_select")
                    return "start"

        renderer.set_surface(sync_window_size(window, BaseRenderer.window_size()))
        renderer.draw(base, progress, pygame.mouse.get_pos())
        pygame.display.flip()
        clock.tick(FPS)
        await asyncio.sleep(0)


async def run_progression_mode(window: "Window | None", clock: pygame.time.Clock) -> str:
    """
    Owns the Base<->run loop: the Base always precedes a run, and R after a
    fail/complete screen loops back into it (see run_labyrinth()) rather
    than restarting in place. main.py only ever sees "quit"/"menu" from
    this -- the same contract every other mode's entry point exposes.
    """
    while True:
        base_result = await run_base(window, clock)
        if base_result in ("quit", "menu"):
            return base_result
        run_result = await run_labyrinth(window, clock)
        if run_result in ("quit", "menu"):
            return run_result
        # run_result == "base" -- loop back to the Base to spend gold before the next run.
