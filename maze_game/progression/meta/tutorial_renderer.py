"""
meta/tutorial_renderer.py
--------------------------
Drawing for the tutorial screens (see tutorial.py): the current step's tiny
maze, its single pellet/goal, the player, and a banner with the step's
teaching message, a countdown (only on the timed final step), and the
always-on "ESC = skip" hint. Mirrors freeplay/renderer.py and
progression/meta/renderer.py's shape -- its own small window, sized to
whichever tutorial step is currently showing rather than a fixed constant,
since the steps deliberately span a couple of different (tiny) dimensions.
"""

import pygame

from maze_game.constants import (
    C_BG, C_WALL, C_FLOOR, C_PLAYER, C_GOAL, C_PELLET,
    C_TEXT, C_DIM, C_FLASH, C_HUD_BG,
)
from maze_game.media import sprites
from maze_game.media.shapes import draw_smiley_face
from maze_game.progression.meta.tutorial import TutorialRun, TUTORIAL_STEPS

MAZE_AREA_SIZE = 360  # fixed pixel viewport the tiny maze renders within
BANNER_HEIGHT = 90

LOW_TIME_WARNING_SECONDS = 5.0


class Layout:
    def __init__(self, cols: int, rows: int) -> None:
        self.cell = max(1, MAZE_AREA_SIZE // max(cols, rows))
        self.maze_w = cols * self.cell
        self.maze_h = rows * self.cell
        self.window_w = MAZE_AREA_SIZE
        self.window_h = MAZE_AREA_SIZE + BANNER_HEIGHT
        # Centered within the fixed viewport -- a 5x5 step's maze is much
        # smaller than the viewport, unlike progression/renderer.py's Layout
        # where cell size alone absorbs every dimension change.
        self.maze_origin = ((self.window_w - self.maze_w) // 2, (MAZE_AREA_SIZE - self.maze_h) // 2)
        self.banner = pygame.Rect(0, MAZE_AREA_SIZE, self.window_w, BANNER_HEIGHT)


class TutorialRenderer:
    def __init__(self, surface: pygame.Surface) -> None:
        self.surface = surface
        self.font_big = pygame.font.SysFont("monospace", 18, bold=True)
        self.font_small = pygame.font.SysFont("monospace", 14)
        self.font_huge = pygame.font.SysFont("monospace", 28, bold=True)

    def set_surface(self, surface: pygame.Surface) -> None:
        self.surface = surface

    @staticmethod
    def window_size(cols: int, rows: int) -> tuple[int, int]:
        layout = Layout(cols, rows)
        return layout.window_w, layout.window_h

    def draw(self, run: TutorialRun) -> None:
        layout = Layout(run.cols, run.rows)
        self.surface.fill(C_BG)

        self._draw_maze(run.grid, layout)
        self._draw_goal(run.goal, layout)
        if run.pellet is not None:
            self._draw_pellet(run.pellet, layout)
        self._draw_player(run.player, layout)
        self._draw_banner(run, layout)

        if run.step_failed:
            self._draw_retry_overlay(layout)

    # ── Maze / entities ──────────────────────────────────────────────────

    def _draw_maze(self, grid, layout: Layout) -> None:
        ox, oy = layout.maze_origin
        cell = layout.cell
        for row in range(len(grid)):
            for col in range(len(grid[0])):
                colour = C_WALL if grid[row][col] == 1 else C_FLOOR
                pygame.draw.rect(self.surface, colour, pygame.Rect(ox + col * cell, oy + row * cell, cell, cell))

    def _draw_goal(self, goal, layout: Layout) -> None:
        ox, oy = layout.maze_origin
        cell = layout.cell
        gx, gy = goal
        icon = sprites.get("goal", cell)
        if icon is not None:
            self.surface.blit(icon, (ox + gx * cell, oy + gy * cell))
            return
        pad = max(1, cell // 7)
        pygame.draw.ellipse(self.surface, C_GOAL, pygame.Rect(ox + gx * cell + pad, oy + gy * cell + pad, cell - 2 * pad, cell - 2 * pad))

    def _draw_pellet(self, pellet, layout: Layout) -> None:
        ox, oy = layout.maze_origin
        cell = layout.cell
        x, y = pellet
        icon = sprites.get("pellet", cell)
        if icon is not None:
            self.surface.blit(icon, (ox + x * cell, oy + y * cell))
            return
        r = max(1, cell // 5)
        pygame.draw.circle(self.surface, C_PELLET, (ox + x * cell + cell // 2, oy + y * cell + cell // 2), r)

    def _draw_player(self, player, layout: Layout) -> None:
        ox, oy = layout.maze_origin
        cell = layout.cell
        px, py = player
        icon = sprites.get("player", cell)
        if icon is not None:
            self.surface.blit(icon, (ox + px * cell, oy + py * cell))
            return
        center = (ox + px * cell + cell // 2, oy + py * cell + cell // 2)
        radius = max(1, cell // 2 - 3)
        pygame.draw.circle(self.surface, C_PLAYER, center, radius)
        draw_smiley_face(self.surface, C_BG, center, radius)

    # ── Banner ───────────────────────────────────────────────────────────

    def _draw_banner(self, run: TutorialRun, layout: Layout) -> None:
        pygame.draw.rect(self.surface, C_HUD_BG, layout.banner)

        step_label = self.font_small.render(f"Tutorial {run.step_index + 1}/{len(TUTORIAL_STEPS)}", True, C_DIM)
        self.surface.blit(step_label, (layout.banner.x + 10, layout.banner.y + 6))

        if run.timer is not None:
            remaining = max(0.0, run.timer.remaining)
            colour = C_FLASH if remaining <= LOW_TIME_WARNING_SECONDS else C_TEXT
            timer_label = self.font_big.render(f"{remaining:4.1f}s", True, colour)
            self.surface.blit(timer_label, (layout.banner.right - timer_label.get_width() - 10, layout.banner.y + 4))

        msg = self.font_big.render(run.step.message, True, C_TEXT)
        self.surface.blit(msg, msg.get_rect(center=(layout.banner.centerx, layout.banner.y + 42)))

        hint = self.font_small.render("ESC = skip tutorial", True, C_DIM)
        self.surface.blit(hint, (layout.banner.x + 10, layout.banner.bottom - 20))

    # ── Overlay ──────────────────────────────────────────────────────────

    def _draw_retry_overlay(self, layout: Layout) -> None:
        overlay = pygame.Surface((layout.window_w, MAZE_AREA_SIZE), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 180))
        self.surface.blit(overlay, (0, 0))

        title = self.font_huge.render("Time's up!", True, C_TEXT)
        subtitle = self.font_small.render("SPACE = try again     ESC = skip tutorial", True, C_DIM)
        cx, cy = layout.window_w // 2, MAZE_AREA_SIZE // 2
        self.surface.blit(title, title.get_rect(center=(cx, cy - 16)))
        self.surface.blit(subtitle, subtitle.get_rect(center=(cx, cy + 20)))
