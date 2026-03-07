"""
renderer.py
-----------
All pygame drawing code.  The Renderer class knows nothing about game rules —
it simply takes state and paints it to a surface.
"""

import pygame
from maze_game.constants import (
    CELL, COLS, ROWS, WIDTH,
    C_BG, C_WALL, C_FLOOR, C_PLAYER, C_GOAL,
    C_TEXT, C_DIM, C_FLASH, C_HUD_BG,
)


class Renderer:
    """Handles all drawing for the maze game."""

    def __init__(self, surface: pygame.Surface) -> None:
        self.surface   = surface
        self.font_big  = pygame.font.SysFont("monospace", 20, bold=True)
        self.font_small = pygame.font.SysFont("monospace", 14)

    # ── Public API ────────────────────────────────────────────────────────

    def draw(
        self,
        grid: list[list[int]],
        player: tuple[int, int],
        goal: tuple[int, int],
        elapsed: float,
        best_time: float | None,
        finished: bool,
    ) -> None:
        """Render a complete frame."""
        self.surface.fill(C_BG)
        self._draw_maze(grid)
        self._draw_goal(goal)
        self._draw_player(player)
        self._draw_hud(elapsed, best_time, finished)

    # ── Private helpers ───────────────────────────────────────────────────

    def _draw_maze(self, grid: list[list[int]]) -> None:
        for row in range(ROWS):
            for col in range(COLS):
                colour = C_WALL if grid[row][col] == 1 else C_FLOOR
                pygame.draw.rect(
                    self.surface,
                    colour,
                    pygame.Rect(col * CELL, row * CELL, CELL, CELL),
                )

    def _draw_goal(self, goal: tuple[int, int]) -> None:
        gx, gy = goal
        pygame.draw.ellipse(
            self.surface,
            C_GOAL,
            pygame.Rect(gx * CELL + 4, gy * CELL + 4, CELL - 8, CELL - 8),
        )

    def _draw_player(self, player: tuple[int, int]) -> None:
        px, py = player
        pygame.draw.circle(
            self.surface,
            C_PLAYER,
            (px * CELL + CELL // 2, py * CELL + CELL // 2),
            CELL // 2 - 3,
        )

    def _draw_hud(
        self,
        elapsed: float,
        best_time: float | None,
        finished: bool,
    ) -> None:
        bar_y = ROWS * CELL
        pygame.draw.rect(self.surface, C_HUD_BG, (0, bar_y, WIDTH, 60))

        if finished:
            label  = f"Done!  {elapsed:.2f}s"
            if best_time is not None:
                label += f"   (best: {best_time:.2f}s)"
            label += "   R = new maze"
            colour = C_FLASH
        else:
            label  = f"{elapsed:.1f}s"
            colour = C_TEXT

        self.surface.blit(
            self.font_big.render(label, True, colour),
            (10, bar_y + 10),
        )

        if best_time is not None and not finished:
            best_surf = self.font_small.render(
                f"best: {best_time:.2f}s", True, C_DIM
            )
            self.surface.blit(
                best_surf,
                (WIDTH - best_surf.get_width() - 10, bar_y + 18),
            )

        hint = self.font_small.render(
            "arrows=move   r=new maze   esc=quit", True, C_DIM
        )
        self.surface.blit(hint, (10, bar_y + 42))
