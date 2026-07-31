"""
renderer.py
-----------
All pygame drawing code for the labyrinth progression mode: the maze,
pellets/enemies/boss/teleporter pads, HUD (time resource + maze/group
progress + seed), the left sidebar (acquired perks, the 4 fixed Q/W/E/R
item slots, and up to MAX_ACTIVE_AUGMENTS maze-modifier slots -- perks/items
always draw their entire static catalog filled-or-not, augments draw only
as many slots as can ever be simultaneously active), and the break-card
screen that replaces the maze area during a power-up or maze-modifier
break (`_draw_break_cards`, branching on `run.break_kind`). Layout owns the
rect geometry so progression/app.py::run_labyrinth()'s click hit-testing
(break cards) uses the same rects draw() paints with, mirroring
freeplay/renderer.py's convention.

The window is a fixed size regardless of maze dimensions: the maze renders
inside a static MAZE_AREA_SIZE viewport, with per-cell pixel size shrinking
to fit as the maze grows (9x9 up to 41x41 over the run) rather than the
window itself growing. Keeps the window (and the shop-card/sidebar layout,
which don't scale with maze size at all) visually stable across the whole
run.
"""

import time

import pygame

from maze_game.constants import (
    SIDEBAR_W, HUD_HEIGHT, LABYRINTH_TOTAL_MAZES, MAX_ACTIVE_AUGMENTS,
    C_BG, C_WALL, C_FLOOR, C_PLAYER, C_GOAL, C_TEXT, C_DIM, C_FLASH, C_HUD_BG,
    C_PANEL_BG, C_PANEL_LINE, C_BUTTON, C_BUTTON_HOVER,
    C_PELLET, C_ENEMY, C_BOSS_IDLE, C_BOSS_ACTIVE, C_TELEPORT_PAIRS,
    POPUP_DURATION_SECONDS, POPUP_RISE_PIXELS,
)
from maze_game.media import sprites
from maze_game.progression.shop.perks import ALL_PERKS
from maze_game.progression.shop.items import ALL_ITEMS, UNLIMITED_ITEM_IDS
from maze_game.progression.augments import AUGMENTS_BY_ID
from maze_game.progression.run import LabyrinthRun

MAZE_AREA_SIZE = 640  # fixed pixel viewport the maze renders within, at any dimension
LOW_TIME_WARNING_SECONDS = 5.0
SQUEAK_FLASH_SECONDS = 1.0

CARD_MARGIN = 24
CARD_GAP = 16
CARD_PADDING = 12
CARD_LINE_HEIGHT = 18

BUILD_SQUARE_SIZE = 36
BUILD_SQUARE_GAP = 12
ITEMS_TITLE_Y = 180
ITEMS_SUBTITLE_Y = 224
ITEM_SQUARES_Y = 274
AUGMENTS_TITLE_Y = 330
AUGMENTS_SUBTITLE_Y = 374
AUGMENT_SQUARES_Y = 424
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
    """Computed rects for the current cols/rows -- shared by draw() and progression/app.py::run_labyrinth()'s click handling."""

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
        self.build_squares = [
            pygame.Rect(bx + i * (BUILD_SQUARE_SIZE + BUILD_SQUARE_GAP), 110, BUILD_SQUARE_SIZE, BUILD_SQUARE_SIZE)
            for i in range(len(ALL_PERKS))
        ]
        self.item_squares = [
            pygame.Rect(bx + i * (BUILD_SQUARE_SIZE + BUILD_SQUARE_GAP), ITEM_SQUARES_Y, BUILD_SQUARE_SIZE, BUILD_SQUARE_SIZE)
            for i in range(len(ALL_ITEMS))
        ]
        # Sized to MAX_ACTIVE_AUGMENTS fixed slots, not the full (still-growing)
        # augment catalog -- unlike perks/items, which show their entire static
        # catalog filled-or-not, only up to MAX_ACTIVE_AUGMENTS can ever be
        # active at once, so that's the right slot count regardless of how
        # many augments eventually exist.
        self.augment_squares = [
            pygame.Rect(bx + i * (BUILD_SQUARE_SIZE + BUILD_SQUARE_GAP), AUGMENT_SQUARES_Y, BUILD_SQUARE_SIZE, BUILD_SQUARE_SIZE)
            for i in range(MAX_ACTIVE_AUGMENTS)
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
            self._draw_break_cards(run, layout, mouse_pos)
        else:
            self._draw_maze(run.grid, layout)
            self._draw_pellets(run.pellets, layout)
            self._draw_enemies(run.enemies, layout)
            self._draw_teleporters(run.teleporters, layout)
            if run.boss is not None:
                self._draw_boss(run.boss, layout)
            else:
                self._draw_goal(run.goal, layout)
            self._draw_player(run.player, layout)
            self._draw_squeak(run, layout)
            self._draw_popups(run, layout)

        self._draw_hud(run, layout)
        self._draw_build_sidebar(run.build, layout, mouse_pos)
        self._draw_items_sidebar(run.loadout, layout, mouse_pos)
        self._draw_augment_sidebar(run.augment_build, layout, mouse_pos)

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
        icon = sprites.get("goal", cell)
        if icon is not None:
            self.surface.blit(icon, (ox + gx * cell, oy + gy * cell))
            return
        pad = max(1, cell // 7)
        pygame.draw.ellipse(self.surface, C_GOAL, pygame.Rect(ox + gx * cell + pad, oy + gy * cell + pad, cell - 2 * pad, cell - 2 * pad))

    def _draw_player(self, player, layout: Layout) -> None:
        ox, oy = layout.maze_origin
        cell = layout.cell
        px, py = player
        icon = sprites.get("player", cell)
        if icon is not None:
            self.surface.blit(icon, (ox + px * cell, oy + py * cell))
            return
        pygame.draw.circle(self.surface, C_PLAYER, (ox + px * cell + cell // 2, oy + py * cell + cell // 2), max(1, cell // 2 - 3))

    def _draw_pellets(self, pellets, layout: Layout) -> None:
        ox, oy = layout.maze_origin
        cell = layout.cell
        icon = sprites.get("pellet", cell)
        for pellet in pellets:
            x, y = pellet.pos
            if icon is not None:
                self.surface.blit(icon, (ox + x * cell, oy + y * cell))
                continue
            r = max(1, cell // 5)
            pygame.draw.circle(self.surface, C_PELLET, (ox + x * cell + cell // 2, oy + y * cell + cell // 2), r)

    def _draw_enemies(self, enemies, layout: Layout) -> None:
        ox, oy = layout.maze_origin
        cell = layout.cell
        pad = max(1, cell // 5)
        icon = sprites.get("enemy", cell)
        for enemy in enemies:
            x, y = enemy.pos
            if icon is not None:
                self.surface.blit(icon, (ox + x * cell, oy + y * cell))
                continue
            pygame.draw.rect(
                self.surface, C_ENEMY,
                pygame.Rect(ox + x * cell + pad, oy + y * cell + pad, cell - 2 * pad, cell - 2 * pad),
            )

    def _draw_teleporters(self, teleporters, layout: Layout) -> None:
        ox, oy = layout.maze_origin
        cell = layout.cell
        pad = max(1, cell // 5)
        for pair in teleporters:
            colour = C_TELEPORT_PAIRS[pair.color_index % len(C_TELEPORT_PAIRS)]
            for x, y in (pair.a, pair.b):
                rect = pygame.Rect(ox + x * cell + pad, oy + y * cell + pad, cell - 2 * pad, cell - 2 * pad)
                pygame.draw.rect(self.surface, colour, rect, width=max(2, cell // 8))

    def _draw_boss(self, boss, layout: Layout) -> None:
        ox, oy = layout.maze_origin
        cell = layout.cell
        x, y = boss.pos
        icon_name = "boss_idle" if boss.phase == "idle" else "boss_active"
        icon = sprites.get(icon_name, cell)
        if icon is not None:
            self.surface.blit(icon, (ox + x * cell, oy + y * cell))
        else:
            pad = max(1, cell // 10)
            colour = C_BOSS_IDLE if boss.phase == "idle" else C_BOSS_ACTIVE
            pygame.draw.ellipse(self.surface, colour, pygame.Rect(ox + x * cell + pad, oy + y * cell + pad, cell - 2 * pad, cell - 2 * pad))
        hp_label = self.font_small.render(f"HP {max(0, boss.hp):g}", True, C_TEXT)
        self.surface.blit(hp_label, (ox + x * cell - hp_label.get_width() // 2 + cell // 2, oy + y * cell - 18))

    def _draw_squeak(self, run: LabyrinthRun, layout: Layout) -> None:
        if run.last_squeak_at is None or time.monotonic() - run.last_squeak_at > SQUEAK_FLASH_SECONDS:
            return
        ox, oy = layout.maze_origin
        cell = layout.cell
        px, py = run.player
        label = self.font_big.render("Squeak!", True, C_FLASH)
        self.surface.blit(label, (ox + px * cell + cell // 2 - label.get_width() // 2, oy + py * cell - cell))

    def _draw_popups(self, run: LabyrinthRun, layout: Layout) -> None:
        """Floating "+Xs"/"-Xs" labels for pellet/enemy/speed-bonus time changes -- rises and fades out over its lifetime."""
        ox, oy = layout.maze_origin
        cell = layout.cell
        now = time.monotonic()
        for popup in run.popups:
            age = now - popup.created_at
            if age >= POPUP_DURATION_SECONDS:
                continue
            progress = age / POPUP_DURATION_SECONDS
            rise = int(POPUP_RISE_PIXELS * progress)
            x, y = popup.pos
            label = self.font_small.render(popup.text, True, popup.color)
            px = ox + x * cell + cell // 2 - label.get_width() // 2
            py = oy + y * cell - cell // 2 - rise
            self.surface.blit(label, (px, py))

    # ── HUD ──────────────────────────────────────────────────────────────

    def _draw_hud(self, run: LabyrinthRun, layout: Layout) -> None:
        pygame.draw.rect(self.surface, C_HUD_BG, layout.hud)

        remaining = run.time.amount
        colour = C_FLASH if remaining <= LOW_TIME_WARNING_SECONDS else C_TEXT
        timer_label = self.font_big.render(f"{remaining:4.1f}s", True, colour)
        self.surface.blit(timer_label, (layout.hud.x + 10, layout.hud.y + 8))

        progress = self.font_small.render(
            f"Maze {run.maze_index}/{LABYRINTH_TOTAL_MAZES}   ({run.cols}x{run.rows})   "
            f"group {run.group_number}/{run.total_groups}   seed {run.seed}",
            True, C_DIM,
        )
        self.surface.blit(progress, (layout.hud.x + 10, layout.hud.y + 36))

    # ── Build sidebar (passive perks) ─────────────────────────────────────

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
                hovered = (perk.name, perk.description, count)

        if hovered is not None:
            self._draw_tooltip(*hovered, mouse_pos)

    # ── Items sidebar (Q/W/E/R active abilities) ──────────────────────────

    def _draw_items_sidebar(self, loadout, layout: Layout, mouse_pos) -> None:
        title = self.font_big.render("ITEMS", True, C_TEXT)
        self.surface.blit(title, (layout.left.x + 16, ITEMS_TITLE_Y))
        section = self.font_small.render("Q/W/E/R to use", True, C_DIM)
        self.surface.blit(section, (layout.left.x + 16, ITEMS_SUBTITLE_Y))

        hovered = None
        for item, rect in zip(ALL_ITEMS, layout.item_squares):
            count = loadout.picks.get(item.id, 0)
            acquired = count > 0
            colour = C_BUTTON_HOVER if (acquired and rect.collidepoint(mouse_pos)) else (C_BUTTON if acquired else C_PANEL_LINE)
            pygame.draw.rect(self.surface, colour, rect, border_radius=4)

            letter = self.font_small.render(item.slot_key, True, C_TEXT if acquired else C_DIM)
            self.surface.blit(letter, (rect.x + 4, rect.y + 4))

            if acquired and item.id not in UNLIMITED_ITEM_IDS:
                charges = loadout.charges.get(item.id, 0)
                badge = self.font_small.render(str(charges), True, C_TEXT)
                self.surface.blit(badge, (rect.right - badge.get_width() - 4, rect.bottom - badge.get_height() - 2))

            if acquired and rect.collidepoint(mouse_pos):
                charge_label = "unlimited" if item.id in UNLIMITED_ITEM_IDS else f"x{loadout.charges.get(item.id, 0)} charges"
                hovered = (f"{item.name} ({item.slot_key})", f"{item.description} [{charge_label}]", None)

        if hovered is not None:
            name_line, desc_line, _ = hovered
            self._draw_tooltip(name_line, desc_line, None, mouse_pos)

    # ── Augments sidebar (maze modifiers) ─────────────────────────────────

    def _draw_augment_sidebar(self, augment_build, layout: Layout, mouse_pos) -> None:
        title = self.font_big.render("AUGMENTS", True, C_TEXT)
        self.surface.blit(title, (layout.left.x + 16, AUGMENTS_TITLE_Y))
        section = self.font_small.render("Maze modifiers, chosen every 10 mazes", True, C_DIM)
        self.surface.blit(section, (layout.left.x + 16, AUGMENTS_SUBTITLE_Y))

        active_ids = augment_build.active_ids
        hovered = None
        for i, rect in enumerate(layout.augment_squares):
            acquired = i < len(active_ids)
            colour = C_BUTTON_HOVER if (acquired and rect.collidepoint(mouse_pos)) else (C_BUTTON if acquired else C_PANEL_LINE)
            pygame.draw.rect(self.surface, colour, rect, border_radius=4)
            if not acquired:
                continue

            augment_id = active_ids[i]
            level = augment_build.level_of(augment_id)
            badge = self.font_small.render(str(level), True, C_TEXT)
            self.surface.blit(badge, (rect.right - badge.get_width() - 4, rect.bottom - badge.get_height() - 2))

            if rect.collidepoint(mouse_pos):
                augment = AUGMENTS_BY_ID.get(augment_id)
                if augment is not None:
                    hovered = (augment.name, augment.description, level)

        if hovered is not None:
            self._draw_tooltip(*hovered, mouse_pos)

    def _draw_tooltip(self, name: str, description: str, count: int | None, mouse_pos) -> None:
        name_line = f"{name} (x{count})" if count is not None else name
        desc_lines = _wrap_text(self.font_small, description, TOOLTIP_MAX_WIDTH - 2 * TOOLTIP_PADDING)
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

    # ── Break cards (power-up or maze-modifier break) ─────────────────────

    def _draw_break_cards(self, run: LabyrinthRun, layout: Layout, mouse_pos) -> None:
        is_augment = run.break_kind == "augment"
        choices = run.augment_choices if is_augment else run.shop_choices
        hint_text = (
            f"Maze {run.maze_index} -- choose a maze modifier (arrows + space, click, or 1/2/3)"
            if is_augment else
            f"Group {run.group_number}/{run.total_groups} complete -- pick a card "
            "(arrows + space, click, or 1/2/3)"
        )
        hint = self.font_small.render(hint_text, True, C_DIM)
        self.surface.blit(hint, (layout.left.right + 16, 0))

        for i, (card, rect) in enumerate(zip(choices or [], layout.cards)):
            selected = rect.collidepoint(mouse_pos) or i == run.break_cursor
            pygame.draw.rect(self.surface, C_BUTTON_HOVER if selected else C_BUTTON, rect, border_radius=6)
            pygame.draw.rect(self.surface, C_FLASH if i == run.break_cursor else C_PANEL_LINE, rect, width=2, border_radius=6)

            text_w = rect.width - 2 * CARD_PADDING

            index_label = self.font_small.render(f"[{i + 1}]", True, C_DIM)
            self.surface.blit(index_label, (rect.x + CARD_PADDING, rect.y + CARD_PADDING))

            name = self.font_big.render(card.name, True, C_TEXT)
            self.surface.blit(name, (rect.x + CARD_PADDING, rect.y + CARD_PADDING + 28))

            description = card.description
            if is_augment:
                level = run.augment_build.level_of(card.id)
                if level > 0:
                    description = f"{description} (currently level {level})"

            desc_y = rect.y + CARD_PADDING + 28 + 34
            for line in _wrap_text(self.font_small, description, text_w):
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
