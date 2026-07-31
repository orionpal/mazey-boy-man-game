"""
renderer.py
-----------
All pygame drawing code, plus the layout math for the three-column window
(left sidebar / maze / right sidebar / bottom HUD). The Renderer knows
nothing about game rules -- it takes state and paints it, but it *does* own
the layout geometry, since freeplay/app.py::run_freeplay() needs the same
button rects for click hit-testing that draw() uses for painting (single
source of truth, computed by `Renderer.layout`).
"""

import pygame

from maze_game.constants import (
    CELL, SIDEBAR_W, HUD_HEIGHT, MAX_HISTORY_SHOWN,
    C_BG, C_WALL, C_FLOOR, C_PLAYER, C_GOAL,
    C_TEXT, C_DIM, C_FLASH, C_HUD_BG,
    C_PANEL_BG, C_PANEL_LINE, C_BUTTON, C_BUTTON_HOVER,
)

BUTTON_SIZE = 28
LEFT_CONTENT_HEIGHT = 260   # height needed for the (fixed) left sidebar controls
RIGHT_HEADER_HEIGHT = 56    # "HISTORY" title + top padding, before the first entry
RIGHT_ENTRY_HEIGHT  = 44    # vertical space per history row
RIGHT_BOTTOM_PADDING = 16


class Layout:
    """
    Computed rects for the current cols/rows (and history length) -- shared
    by draw() and freeplay/app.py::run_freeplay()'s click handling.

    Window height must fit whichever is tallest: the maze+HUD column, the
    left sidebar's controls, or the right sidebar's history list. Previously
    this only considered the maze, so a small maze with several history
    entries would draw history text past the bottom of the window and into
    the HUD bar -- passing `history_count` in lets the right sidebar's
    actual content height be part of that max().
    """

    def __init__(self, cols: int, rows: int, history_count: int = 0) -> None:
        self.maze_w = cols * CELL
        self.maze_h = rows * CELL

        shown = min(history_count, MAX_HISTORY_SHOWN)
        right_content_h = RIGHT_HEADER_HEIGHT + shown * RIGHT_ENTRY_HEIGHT + RIGHT_BOTTOM_PADDING

        self.window_h = max(self.maze_h + HUD_HEIGHT, LEFT_CONTENT_HEIGHT, right_content_h)
        self.window_w = SIDEBAR_W + self.maze_w + SIDEBAR_W

        # Sidebars always span the full window height, so their background
        # can never end above the HUD or above their own content.
        self.left = pygame.Rect(0, 0, SIDEBAR_W, self.window_h)
        self.maze_origin = (SIDEBAR_W, 0)
        self.right = pygame.Rect(SIDEBAR_W + self.maze_w, 0, SIDEBAR_W, self.window_h)
        self.hud = pygame.Rect(SIDEBAR_W, self.maze_h, self.maze_w, HUD_HEIGHT)

        # Left sidebar: cols/rows +/- buttons.
        bx = self.left.x + 16
        self.cols_minus = pygame.Rect(bx, 100, BUTTON_SIZE, BUTTON_SIZE)
        self.cols_plus  = pygame.Rect(bx + 130, 100, BUTTON_SIZE, BUTTON_SIZE)
        self.rows_minus = pygame.Rect(bx, 168, BUTTON_SIZE, BUTTON_SIZE)
        self.rows_plus  = pygame.Rect(bx + 130, 168, BUTTON_SIZE, BUTTON_SIZE)


class Renderer:
    """Handles all drawing for the maze game."""

    def __init__(self, surface: pygame.Surface) -> None:
        self.surface     = surface
        self.font_big    = pygame.font.SysFont("monospace", 20, bold=True)
        self.font_small  = pygame.font.SysFont("monospace", 14)
        self.font_button = pygame.font.SysFont("monospace", 20, bold=True)

    def set_surface(self, surface: pygame.Surface) -> None:
        """Call after pygame.display.set_mode() returns a resized surface."""
        self.surface = surface

    @staticmethod
    def window_size(cols: int, rows: int, history_count: int = 0) -> tuple[int, int]:
        layout = Layout(cols, rows, history_count)
        return layout.window_w, layout.window_h

    # ── Public API ────────────────────────────────────────────────────────

    def draw(
        self,
        grid: list[list[int]],
        player: tuple[int, int],
        goal: tuple[int, int],
        elapsed: float,
        best_time: float | None,
        finished: bool,
        cols: int,
        rows: int,
        history: list,
    ) -> None:
        """Render a complete frame."""
        layout = Layout(cols, rows, len(history))
        mouse_pos = pygame.mouse.get_pos()

        self.surface.fill(C_BG)
        self._draw_maze(grid, layout)
        self._draw_goal(goal, layout)
        self._draw_player(player, layout)
        self._draw_hud(elapsed, best_time, finished, layout)
        self._draw_left_sidebar(cols, rows, layout, mouse_pos)
        self._draw_right_sidebar(history, layout)

    # ── Private helpers ───────────────────────────────────────────────────

    def _draw_maze(self, grid, layout: Layout) -> None:
        ox, oy = layout.maze_origin
        for row in range(len(grid)):
            for col in range(len(grid[0])):
                colour = C_WALL if grid[row][col] == 1 else C_FLOOR
                pygame.draw.rect(
                    self.surface,
                    colour,
                    pygame.Rect(ox + col * CELL, oy + row * CELL, CELL, CELL),
                )

    def _draw_goal(self, goal, layout: Layout) -> None:
        ox, oy = layout.maze_origin
        gx, gy = goal
        pygame.draw.ellipse(
            self.surface,
            C_GOAL,
            pygame.Rect(ox + gx * CELL + 4, oy + gy * CELL + 4, CELL - 8, CELL - 8),
        )

    def _draw_player(self, player, layout: Layout) -> None:
        ox, oy = layout.maze_origin
        px, py = player
        pygame.draw.circle(
            self.surface,
            C_PLAYER,
            (ox + px * CELL + CELL // 2, oy + py * CELL + CELL // 2),
            CELL // 2 - 3,
        )

    def _draw_hud(self, elapsed, best_time, finished, layout: Layout) -> None:
        pygame.draw.rect(self.surface, C_HUD_BG, layout.hud)

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
            (layout.hud.x + 10, layout.hud.y + 10),
        )

        if best_time is not None and not finished:
            best_surf = self.font_small.render(f"best: {best_time:.2f}s", True, C_DIM)
            self.surface.blit(
                best_surf,
                (layout.hud.right - best_surf.get_width() - 10, layout.hud.y + 18),
            )

        hint = self.font_small.render(
            "arrows=move   r=new maze   esc=quit", True, C_DIM
        )
        self.surface.blit(hint, (layout.hud.x + 10, layout.hud.y + 42))

    def _draw_left_sidebar(self, cols: int, rows: int, layout: Layout, mouse_pos) -> None:
        pygame.draw.rect(self.surface, C_PANEL_BG, layout.left)
        pygame.draw.line(
            self.surface, C_PANEL_LINE,
            (layout.left.right, 0), (layout.left.right, layout.left.height), 2,
        )

        title = self.font_big.render("MAZE", True, C_TEXT)
        self.surface.blit(title, (layout.left.x + 16, 16))

        section = self.font_small.render("Dimensions", True, C_DIM)
        self.surface.blit(section, (layout.left.x + 16, 60))

        self._draw_stepper(f"Cols: {cols}", layout.cols_minus, layout.cols_plus, mouse_pos)
        self._draw_stepper(f"Rows: {rows}", layout.rows_minus, layout.rows_plus, mouse_pos)

        hint = self.font_small.render("click +/- to resize", True, C_DIM)
        self.surface.blit(hint, (layout.left.x + 16, 214))
        hint2 = self.font_small.render("(starts a new maze)", True, C_DIM)
        self.surface.blit(hint2, (layout.left.x + 16, 231))

    def _draw_stepper(self, label: str, minus_rect, plus_rect, mouse_pos) -> None:
        label_surf = self.font_small.render(label, True, C_TEXT)
        self.surface.blit(label_surf, (minus_rect.x, minus_rect.y - 24))
        self._draw_button(minus_rect, "-", mouse_pos)
        self._draw_button(plus_rect, "+", mouse_pos)

    def _draw_button(self, rect, text: str, mouse_pos) -> None:
        colour = C_BUTTON_HOVER if rect.collidepoint(mouse_pos) else C_BUTTON
        pygame.draw.rect(self.surface, colour, rect, border_radius=4)
        glyph = self.font_button.render(text, True, C_TEXT)
        glyph_rect = glyph.get_rect(center=rect.center)
        self.surface.blit(glyph, glyph_rect)

    def _draw_right_sidebar(self, history: list, layout: Layout) -> None:
        pygame.draw.rect(self.surface, C_PANEL_BG, layout.right)
        pygame.draw.line(
            self.surface, C_PANEL_LINE,
            (layout.right.x, 0), (layout.right.x, layout.right.height), 2,
        )

        title = self.font_big.render("HISTORY", True, C_TEXT)
        self.surface.blit(title, (layout.right.x + 16, 16))

        if not history:
            empty = self.font_small.render("No runs yet", True, C_DIM)
            self.surface.blit(empty, (layout.right.x + 16, 56))
            return

        y = 56
        for record in history[:MAX_HISTORY_SHOWN]:
            dims_line = self.font_small.render(f"{record.cols}x{record.rows}", True, C_TEXT)
            self.surface.blit(dims_line, (layout.right.x + 16, y))

            stats_line = self.font_small.render(
                f"{record.seconds:.2f}s   {record.date_label}", True, C_DIM
            )
            self.surface.blit(stats_line, (layout.right.x + 16, y + 18))

            y += 44
