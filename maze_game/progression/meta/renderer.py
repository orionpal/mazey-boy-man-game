"""
renderer.py
-----------
Drawing for the Base screen -- gold total, one tile per meta upgrade
(owned level, next cost, description), and a Start Run action. Mirrors
menu/renderer.py's simplicity: its own small fixed window size, independent
of the maze layouts that only get sized once a run actually exists.
"""

import pygame

from maze_game.constants import (
    C_BG, C_TEXT, C_DIM, C_CARD_DESC, C_GOLD, C_FLASH,
    C_PANEL_LINE, C_BUTTON, C_BUTTON_HOVER,
)
from maze_game.progression.meta import ALL_META_UPGRADES, Base, MetaProgress

WINDOW_W = 640
WINDOW_H = 440

TILE_W = 260
TILE_H = 160
TILE_GAP = 24
TILES_Y = 140
TILE_LINE_HEIGHT = 18

START_BUTTON_W = 240
START_BUTTON_H = 56
START_BUTTON_Y = 330


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


class BaseRenderer:
    def __init__(self, surface: pygame.Surface) -> None:
        self.surface = surface
        self.font_huge = pygame.font.SysFont("monospace", 32, bold=True)
        self.font_big = pygame.font.SysFont("monospace", 20, bold=True)
        self.font_small = pygame.font.SysFont("monospace", 14)

    def set_surface(self, surface: pygame.Surface) -> None:
        self.surface = surface

    @staticmethod
    def window_size() -> tuple[int, int]:
        return WINDOW_W, WINDOW_H

    def tile_rects(self) -> list[pygame.Rect]:
        """Shared by draw() and progression/app.py::run_base()'s click handling."""
        count = len(ALL_META_UPGRADES)
        total_w = count * TILE_W + (count - 1) * TILE_GAP
        x0 = (WINDOW_W - total_w) // 2
        return [pygame.Rect(x0 + i * (TILE_W + TILE_GAP), TILES_Y, TILE_W, TILE_H) for i in range(count)]

    def start_button_rect(self) -> pygame.Rect:
        return pygame.Rect((WINDOW_W - START_BUTTON_W) // 2, START_BUTTON_Y, START_BUTTON_W, START_BUTTON_H)

    def draw(self, base: Base, progress: MetaProgress, mouse_pos: tuple[int, int]) -> None:
        self.surface.fill(C_BG)

        title = self.font_huge.render("BASE", True, C_TEXT)
        self.surface.blit(title, title.get_rect(center=(WINDOW_W // 2, 46)))

        gold_label = self.font_big.render(f"{progress.gold}g", True, C_GOLD)
        self.surface.blit(gold_label, gold_label.get_rect(center=(WINDOW_W // 2, 90)))

        for i, (upgrade, rect) in enumerate(zip(ALL_META_UPGRADES, self.tile_rects())):
            selected = i == base.cursor
            hovered = rect.collidepoint(mouse_pos)
            colour = C_BUTTON_HOVER if (selected or hovered) else C_BUTTON
            pygame.draw.rect(self.surface, colour, rect, border_radius=8)
            pygame.draw.rect(self.surface, C_FLASH if selected else C_PANEL_LINE, rect, width=2, border_radius=8)

            level = progress.level_of(upgrade)
            cost = progress.cost_for(upgrade)
            affordable = progress.can_afford(upgrade)

            name = self.font_big.render(upgrade.name, True, C_TEXT)
            self.surface.blit(name, (rect.x + 12, rect.y + 10))

            level_label = self.font_small.render(f"Level {level}", True, C_CARD_DESC)
            self.surface.blit(level_label, (rect.x + 12, rect.y + 40))

            cost_label = self.font_small.render(f"Cost: {cost}g", True, C_GOLD if affordable else C_DIM)
            self.surface.blit(cost_label, (rect.x + 12, rect.y + 58))

            desc_y = rect.y + 82
            for line in _wrap_text(self.font_small, upgrade.description, TILE_W - 24):
                surf = self.font_small.render(line, True, C_CARD_DESC)
                self.surface.blit(surf, (rect.x + 12, desc_y))
                desc_y += TILE_LINE_HEIGHT

        start_rect = self.start_button_rect()
        start_selected = base.on_start_run
        start_hovered = start_rect.collidepoint(mouse_pos)
        colour = C_BUTTON_HOVER if (start_selected or start_hovered) else C_BUTTON
        pygame.draw.rect(self.surface, colour, start_rect, border_radius=8)
        pygame.draw.rect(self.surface, C_FLASH if start_selected else C_PANEL_LINE, start_rect, width=2, border_radius=8)
        start_label = self.font_big.render("Start Run", True, C_TEXT)
        self.surface.blit(start_label, start_label.get_rect(center=start_rect.center))

        hint = self.font_small.render(
            "arrows/click to choose, space/enter to confirm, ESC to quit", True, C_DIM,
        )
        self.surface.blit(hint, hint.get_rect(center=(WINDOW_W // 2, WINDOW_H - 20)))
