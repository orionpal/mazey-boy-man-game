"""
renderer.py
-----------
All pygame drawing code for the labyrinth progression mode: the maze,
pellets/enemies/boss, HUD (time resource + maze/group progress), the left
"build" sidebar (acquired perks, hover for a description), and the perk-card
screen that replaces the maze area during a group break. Layout owns the
rect geometry so main.py's click hit-testing (perk cards) uses the same
rects draw() paints with, mirroring freeplay/renderer.py's convention.

The window is a fixed size regardless of maze dimensions: the maze renders
inside a static MAZE_AREA_SIZE viewport, with per-cell pixel size shrinking
to fit as the maze grows (9x9 up to 41x41 over the run) rather than the
window itself growing. Keeps the window (and the perk-card/build-sidebar
layout, which don't scale with maze size at all) visually stable across
the whole run.
"""

import pygame

from maze_game.constants import (
    SIDEBAR_W, HUD_HEIGHT, LABYRINTH_TOTAL_MAZES,
    C_BG, C_WALL, C_FLOOR, C_PLAYER, C_GOAL, C_TEXT, C_DIM, C_FLASH, C_HUD_BG,
    C_PANEL_BG, C_PANEL_LINE, C_BUTTON, C_BUTTON_HOVER,
    C_PELLET, C_ENEMY, C_BOSS_IDLE, C_BOSS_ACTIVE,
)
from maze_game.progression.perks import ALL_PERKS
from maze_game.progression.run import LabyrinthRun

MAZE_AREA_SIZE = 640  # fixed pixel viewport the maze renders within, at any dimension
LOW_TIME_WARNING_SECONDS = 5.0

CARD_MARGIN = 24
CARD_GAP = 16
CARD_PADDING = 12
CARD_LINE_HEIGHT = 18

BUILD_SQUARE_SIZE = 36
BUILD_SQUARE_GAP = 12
TOOLTIP_PADDING = 8
TOOLTIP_MAX_WIDTH = 260


def _wrap_text(font: pygame.font.Font, text: str, max_width: int) -> list[str]:
    """Greedy word-wrap: split `text` into lines no wider than `max_width` pixels."""
    words = text.split(" ")
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if font.size(candidate)[0] <= max_width or not current:
            current = candidate
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


class Layout:
    """Computed rects for the current cols/rows -- shared by draw() and main.py's click handling."""

    def __init__(self, cols: int, rows: int) -> None:
        self.cell = max(1, MAZE_AREA_SIZE // max(cols, rows))
        self.maze_w = cols * self.cell
        self.maze_h = rows * self.cell
        self.window_h = MAZE_AREA_SIZE + HUD_HEIGHT
        self.window_w = SIDEBAR_W + MAZE_AREA_SIZE

        self.left = pygame.Rect(0, 0, SIDEBAR_W, self.window_h)
        self.maze_origin = (SIDEBAR_W, 0)
        self.hud = pygame.Rect(SIDEBAR_W, MAZE_AREA_SIZE, MAZE_AREA_SIZE, HUD_HEIGHT)

        card_area_w = MAZE_AREA_SIZE - 2 * CARD_MARGIN - 2 * CARD_GAP
        card_w = card_area_w // 3
        card_h = MAZE_AREA_SIZE - 2 * CARD_MARGIN
        self.cards = [
            pygame.Rect(SIDEBAR_W + CARD_MARGIN + i * (card_w + CARD_GAP), CARD_MARGIN, card_w, card_h)
            for i in range(3)
        ]

        bx = self.left.x + 16
        by = 110
        self.build_squares = [
            pygame.Rect(bx + i * (BUILD_SQUARE_SIZE + BUILD_SQUARE_GAP), by, BUILD_SQUARE_SIZE, BUILD_SQUARE_SIZE)
            for i in range(len(ALL_PERKS))
        ]


class Renderer:
    def __init__(self, surface: pygame.Surface) -> None:
        self.surface = surface
        self.font_big = pygame.font.SysFont("monospace", 20, bold=True)
        self.font_small = pygame.font.SysFont("monospace", 14)
        self.font_huge = pygame.font.SysFont("monospace", 30, bold=True)
        self.font_button = pygame.font.SysFont("monospace", 20, bold=True)

    def set_surface(self, surface: pygame.Surface) -> None:
        self.surface = surface

    @staticmethod
    def window_size(cols: int, rows: int) -> tuple[int, int]:
        layout = Layout(cols, rows)
        return layout.window_w, layout.window_h

    # ── Public API ────────────────────────────────────────────────────────

    def draw(self, run: LabyrinthRun) -> None:
        layout = Layout(run.cols, run.rows)
        mouse_pos = pygame.mouse.get_pos()

        self.surface.fill(C_BG)

        if run.on_break:
            self._draw_perk_cards(run, layout, mouse_pos)
        else:
            self._draw_maze(run.grid, layout)
            self._draw_pellets(run.pellets, layout)
            self._draw_enemies(run.enemies, layout)
            if run.boss is not None:
                self._draw_boss(run.boss, layout)
            else:
                self._draw_goal(run.goal, layout)
            self._draw_player(run.player, layout)

        self._draw_hud(run, layout)
        self._draw_build_sidebar(run.build, layout, mouse_pos)

        if run.failed:
            self._draw_overlay(
                f"Time's up at maze {run.maze_index}/{LABYRINTH_TOTAL_MAZES}",
                "R = restart from maze 1     ESC = quit",
            )
        elif run.completed_run:
            self._draw_overlay(
                "All 100 mazes complete!",
                "R = play again     ESC = quit",
            )

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
        pad = max(1, cell // 7)
        pygame.draw.ellipse(self.surface, C_GOAL, pygame.Rect(ox + gx * cell + pad, oy + gy * cell + pad, cell - 2 * pad, cell - 2 * pad))

    def _draw_player(self, player, layout: Layout) -> None:
        ox, oy = layout.maze_origin
        cell = layout.cell
        px, py = player
        pygame.draw.circle(self.surface, C_PLAYER, (ox + px * cell + cell // 2, oy + py * cell + cell // 2), max(1, cell // 2 - 3))

    def _draw_pellets(self, pellets, layout: Layout) -> None:
        ox, oy = layout.maze_origin
        cell = layout.cell
        for pellet in pellets:
            x, y = pellet.pos
            r = max(1, cell // 5)
            pygame.draw.circle(self.surface, C_PELLET, (ox + x * cell + cell // 2, oy + y * cell + cell // 2), r)

    def _draw_enemies(self, enemies, layout: Layout) -> None:
        ox, oy = layout.maze_origin
        cell = layout.cell
        pad = max(1, cell // 5)
        for enemy in enemies:
            x, y = enemy.pos
            pygame.draw.rect(
                self.surface, C_ENEMY,
                pygame.Rect(ox + x * cell + pad, oy + y * cell + pad, cell - 2 * pad, cell - 2 * pad),
            )

    def _draw_boss(self, boss, layout: Layout) -> None:
        ox, oy = layout.maze_origin
        cell = layout.cell
        x, y = boss.pos
        pad = max(1, cell // 10)
        colour = C_BOSS_IDLE if boss.phase == "idle" else C_BOSS_ACTIVE
        pygame.draw.ellipse(self.surface, colour, pygame.Rect(ox + x * cell + pad, oy + y * cell + pad, cell - 2 * pad, cell - 2 * pad))
        hp_label = self.font_small.render(f"HP {max(0, boss.hp):g}", True, C_TEXT)
        self.surface.blit(hp_label, (ox + x * cell - hp_label.get_width() // 2 + cell // 2, oy + y * cell - 18))

    # ── HUD ──────────────────────────────────────────────────────────────

    def _draw_hud(self, run: LabyrinthRun, layout: Layout) -> None:
        pygame.draw.rect(self.surface, C_HUD_BG, layout.hud)

        remaining = run.time.amount
        colour = C_FLASH if remaining <= LOW_TIME_WARNING_SECONDS else C_TEXT
        timer_label = self.font_big.render(f"{remaining:4.1f}s", True, colour)
        self.surface.blit(timer_label, (layout.hud.x + 10, layout.hud.y + 8))

        progress = self.font_small.render(
            f"Maze {run.maze_index}/{LABYRINTH_TOTAL_MAZES}   ({run.cols}x{run.rows})   group {run.group_number}/{run.total_groups}",
            True, C_DIM,
        )
        self.surface.blit(progress, (layout.hud.x + 10, layout.hud.y + 36))

    # ── Build sidebar ────────────────────────────────────────────────────

    def _draw_build_sidebar(self, build, layout: Layout, mouse_pos) -> None:
        pygame.draw.rect(self.surface, C_PANEL_BG, layout.left)
        pygame.draw.line(self.surface, C_PANEL_LINE, (layout.left.right, 0), (layout.left.right, layout.left.height), 2)

        title = self.font_big.render("BUILD", True, C_TEXT)
        self.surface.blit(title, (layout.left.x + 16, 16))
        section = self.font_small.render("Hover a perk for details", True, C_DIM)
        self.surface.blit(section, (layout.left.x + 16, 60))

        hovered = None
        for perk, rect in zip(ALL_PERKS, layout.build_squares):
            count = build.picks.get(perk.id, 0)
            acquired = count > 0
            colour = C_BUTTON_HOVER if (acquired and rect.collidepoint(mouse_pos)) else (C_BUTTON if acquired else C_PANEL_LINE)
            pygame.draw.rect(self.surface, colour, rect, border_radius=4)
            if acquired and count > 1:
                badge = self.font_small.render(str(count), True, C_TEXT)
                self.surface.blit(badge, (rect.right - badge.get_width() - 4, rect.bottom - badge.get_height() - 2))
            if acquired and rect.collidepoint(mouse_pos):
                hovered = (perk, count)

        if hovered is not None:
            self._draw_tooltip(hovered[0], hovered[1], mouse_pos)

    def _draw_tooltip(self, perk, count, mouse_pos) -> None:
        name_line = f"{perk.name} (x{count})"
        desc_lines = _wrap_text(self.font_small, perk.description, TOOLTIP_MAX_WIDTH - 2 * TOOLTIP_PADDING)
        lines = [name_line] + desc_lines

        w = max(self.font_small.size(line)[0] for line in lines) + 2 * TOOLTIP_PADDING
        h = len(lines) * CARD_LINE_HEIGHT + 2 * TOOLTIP_PADDING

        x, y = mouse_pos[0] + 12, mouse_pos[1] + 12
        x = min(x, self.surface.get_width() - w)
        y = min(y, self.surface.get_height() - h)
        box = pygame.Rect(x, y, w, h)
        pygame.draw.rect(self.surface, C_PANEL_BG, box, border_radius=4)
        pygame.draw.rect(self.surface, C_PANEL_LINE, box, width=1, border_radius=4)

        name_surf = self.font_small.render(name_line, True, C_TEXT)
        self.surface.blit(name_surf, (x + TOOLTIP_PADDING, y + TOOLTIP_PADDING))
        for i, line in enumerate(desc_lines):
            surf = self.font_small.render(line, True, C_DIM)
            self.surface.blit(surf, (x + TOOLTIP_PADDING, y + TOOLTIP_PADDING + (i + 1) * CARD_LINE_HEIGHT))

    # ── Perk cards (group break) ─────────────────────────────────────────

    def _draw_perk_cards(self, run: LabyrinthRun, layout: Layout, mouse_pos) -> None:
        hint = self.font_small.render(
            f"Group {run.group_number}/{run.total_groups} complete -- pick a perk "
            "(arrows + space, click, or 1/2/3)",
            True, C_DIM,
        )
        self.surface.blit(hint, (layout.left.right + 16, 0))

        for i, (perk, rect) in enumerate(zip(run.perk_choices or [], layout.cards)):
            selected = rect.collidepoint(mouse_pos) or i == run.perk_cursor
            pygame.draw.rect(self.surface, C_BUTTON_HOVER if selected else C_BUTTON, rect, border_radius=6)
            pygame.draw.rect(self.surface, C_FLASH if i == run.perk_cursor else C_PANEL_LINE, rect, width=2, border_radius=6)

            text_w = rect.width - 2 * CARD_PADDING

            index_label = self.font_small.render(f"[{i + 1}]", True, C_DIM)
            self.surface.blit(index_label, (rect.x + CARD_PADDING, rect.y + CARD_PADDING))

            name = self.font_big.render(perk.name, True, C_TEXT)
            self.surface.blit(name, (rect.x + CARD_PADDING, rect.y + CARD_PADDING + 28))

            desc_y = rect.y + CARD_PADDING + 28 + 34
            for line in _wrap_text(self.font_small, perk.description, text_w):
                desc = self.font_small.render(line, True, C_DIM)
                self.surface.blit(desc, (rect.x + CARD_PADDING, desc_y))
                desc_y += CARD_LINE_HEIGHT

    # ── Overlay ──────────────────────────────────────────────────────────

    def _draw_overlay(self, title: str, subtitle: str) -> None:
        overlay = pygame.Surface(self.surface.get_size(), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 180))
        self.surface.blit(overlay, (0, 0))

        title_surf = self.font_huge.render(title, True, C_TEXT)
        subtitle_surf = self.font_small.render(subtitle, True, C_DIM)
        cx, cy = self.surface.get_width() // 2, self.surface.get_height() // 2
        self.surface.blit(title_surf, title_surf.get_rect(center=(cx, cy - 16)))
        self.surface.blit(subtitle_surf, subtitle_surf.get_rect(center=(cx, cy + 20)))
