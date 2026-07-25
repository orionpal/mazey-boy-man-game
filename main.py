"""
main.py
-------
Entry point: the labyrinth progression mode. 100 mazes, gradually
increasing in size, each with its own time limit. Groups of 5 mazes stitch
together seamlessly; a break-and-resume prompt follows each group. Running
out of time on any maze ends the run back at maze 1.

See docs/progression.md for the design decisions behind the starting
numbers (dimensions ramp, time limits, fail behaviour) -- this is a first
guess meant to be played and retuned, not a final balance pass.

For the original single-maze, no-time-limit, adjustable-size free-play mode,
see mvp_main.py instead.

Run with:
    python main.py
"""

import pygame
from pygame._sdl2.video import Window

from maze_game.constants import (
    CELL, HUD_HEIGHT, FPS,
    C_BG, C_WALL, C_FLOOR, C_PLAYER, C_GOAL, C_TEXT, C_DIM, C_FLASH, C_HUD_BG,
    LABYRINTH_TOTAL_MAZES,
)
from maze_game.progression import LabyrinthRun

DIRECTION_MAP: dict[int, tuple[int, int]] = {
    pygame.K_UP:    ( 0, -1),
    pygame.K_DOWN:  ( 0,  1),
    pygame.K_LEFT:  (-1,  0),
    pygame.K_RIGHT: ( 1,  0),
}

LOW_TIME_WARNING_SECONDS = 5.0
MIN_WINDOW_W = 420  # wide enough for the HUD/overlay text even on a 9x9 maze


def window_size(run: LabyrinthRun) -> tuple[int, int]:
    return max(run.cols * CELL, MIN_WINDOW_W), run.rows * CELL + HUD_HEIGHT


def sync_window_size(window: Window, run: LabyrinthRun) -> pygame.Surface:
    """Same in-place-resize approach as mvp_main.py -- see its docstring for why."""
    size = window_size(run)
    if window.size != size:
        window.size = size
    return pygame.display.get_surface()


class Renderer:
    def __init__(self, surface: pygame.Surface) -> None:
        self.surface = surface
        self.font_big = pygame.font.SysFont("monospace", 22, bold=True)
        self.font_small = pygame.font.SysFont("monospace", 15)
        self.font_huge = pygame.font.SysFont("monospace", 30, bold=True)

    def set_surface(self, surface: pygame.Surface) -> None:
        self.surface = surface

    def draw(self, run: LabyrinthRun) -> None:
        self.surface.fill(C_BG)
        maze_w = run.cols * CELL
        for row in range(run.rows):
            for col in range(run.cols):
                colour = C_WALL if run.grid[row][col] == 1 else C_FLOOR
                pygame.draw.rect(self.surface, colour, pygame.Rect(col * CELL, row * CELL, CELL, CELL))

        gx, gy = run.goal
        pygame.draw.ellipse(self.surface, C_GOAL, pygame.Rect(gx * CELL + 4, gy * CELL + 4, CELL - 8, CELL - 8))
        px, py = run.player
        pygame.draw.circle(self.surface, C_PLAYER, (px * CELL + CELL // 2, py * CELL + CELL // 2), CELL // 2 - 3)

        self._draw_hud(run, maze_w)

        if run.on_break:
            self._draw_overlay(
                f"Group {run.group_number}/{run.total_groups} complete!",
                f"Mazes {run.maze_index - 4}-{run.maze_index} done.  SPACE = continue",
            )
        elif run.failed:
            self._draw_overlay(
                f"Time's up at maze {run.maze_index}/{LABYRINTH_TOTAL_MAZES}",
                "R = restart from maze 1     ESC = quit",
            )
        elif run.completed_run:
            self._draw_overlay(
                "All 100 mazes complete!",
                "R = play again     ESC = quit",
            )

    def _draw_hud(self, run: LabyrinthRun, maze_w: int) -> None:
        hud_rect = pygame.Rect(0, run.rows * CELL, self.surface.get_width(), HUD_HEIGHT)
        pygame.draw.rect(self.surface, C_HUD_BG, hud_rect)

        remaining = max(0.0, run.time_limit - run.elapsed)
        colour = C_FLASH if remaining <= LOW_TIME_WARNING_SECONDS and not run.finished else C_TEXT
        timer_label = self.font_big.render(f"{remaining:4.1f}s", True, colour)
        self.surface.blit(timer_label, (10, hud_rect.y + 8))

        progress = self.font_small.render(
            f"Maze {run.maze_index}/{LABYRINTH_TOTAL_MAZES}   ({run.cols}x{run.rows})   group {run.group_number}/{run.total_groups}",
            True, C_DIM,
        )
        self.surface.blit(progress, (10, hud_rect.y + 36))

    def _draw_overlay(self, title: str, subtitle: str) -> None:
        overlay = pygame.Surface(self.surface.get_size(), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 180))
        self.surface.blit(overlay, (0, 0))

        title_surf = self.font_huge.render(title, True, C_TEXT)
        subtitle_surf = self.font_small.render(subtitle, True, C_DIM)
        cx, cy = self.surface.get_width() // 2, self.surface.get_height() // 2
        self.surface.blit(title_surf, title_surf.get_rect(center=(cx, cy - 16)))
        self.surface.blit(subtitle_surf, subtitle_surf.get_rect(center=(cx, cy + 20)))


def main() -> None:
    pygame.init()
    pygame.display.set_caption("Maze -- Labyrinth")
    clock = pygame.time.Clock()

    run = LabyrinthRun()
    screen = pygame.display.set_mode(window_size(run))
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
                elif event.key == pygame.K_SPACE:
                    run.resume()
                elif event.key == pygame.K_r and (run.failed or run.completed_run):
                    run.restart()
                elif event.key in DIRECTION_MAP:
                    run.move(DIRECTION_MAP[event.key])

        run.update()
        renderer.set_surface(sync_window_size(window, run))
        renderer.draw(run)
        pygame.display.flip()
        clock.tick(FPS)

    pygame.quit()


if __name__ == "__main__":
    main()
