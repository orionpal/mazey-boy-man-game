"""
renderer.py
-----------
All pygame drawing code for the labyrinth progression mode: the maze,
pellets/hazards/teleporter pads/doors and keys, HUD (time resource +
maze/group progress + seed), the left sidebar (acquired perks, and up to
MAX_ACTIVE_AUGMENTS maze-modifier slots -- perks draw their entire static
catalog filled-or-not, augments draw only as many slots as can ever be
simultaneously active), and the break-card
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
    C_BG, C_WALL, C_FLOOR, C_PLAYER, C_GOAL, C_TEXT, C_DIM, C_CARD_DESC, C_FLASH, C_HUD_BG,
    C_PANEL_BG, C_PANEL_LINE, C_BUTTON, C_BUTTON_HOVER,
    C_PELLET, C_PELLET_DOUBLE, C_PELLET_VOLATILE, C_PELLET_CHAIN, C_PELLET_FREEZE, C_PELLET_GAMBLE,
    C_GOLD, C_HAZARD, C_TELEPORT_PAIRS, C_DOOR_LOCKED, C_DOOR_UNLOCKED, C_DOOR_KEY_PAIRS,
    C_SPEED_BONUS, C_ROTATE_WARNING, C_PRESSURE_PADS,
    POPUP_DURATION_SECONDS, POPUP_RISE_PIXELS,
    ZIP_ANIMATION_DURATION_SECONDS,
    PELLET_KIND_PLAIN, PELLET_KIND_DOUBLE, PELLET_KIND_VOLATILE,
    PELLET_KIND_CHAIN, PELLET_KIND_FREEZE, PELLET_KIND_GAMBLE,
)
from maze_game.media import sprites
from maze_game.media.shapes import draw_smiley_face
from maze_game.progression.shop.perks import ALL_PERKS
from maze_game.progression.augments import AUGMENTS_BY_ID
from maze_game.progression.run import LabyrinthRun, PauseMenu, PAUSE_OPTIONS

MAZE_AREA_SIZE = 640  # fixed pixel viewport the maze renders within, at any dimension
LOW_TIME_WARNING_SECONDS = 5.0

PELLET_KIND_COLOURS = {
    PELLET_KIND_PLAIN:    C_PELLET,
    PELLET_KIND_DOUBLE:   C_PELLET_DOUBLE,
    PELLET_KIND_VOLATILE: C_PELLET_VOLATILE,
    PELLET_KIND_CHAIN:    C_PELLET_CHAIN,
    PELLET_KIND_FREEZE:   C_PELLET_FREEZE,
    PELLET_KIND_GAMBLE:   C_PELLET_GAMBLE,
}

CARD_MARGIN = 24
CARD_GAP = 16
CARD_PADDING = 12
CARD_LINE_HEIGHT = 18
CARD_NAME_LINE_HEIGHT = 24

PAUSE_OPTION_W = 280
PAUSE_OPTION_H = 56
PAUSE_OPTION_GAP = 16
PAUSE_OPTION_START_Y_OFFSET = 20  # relative to vertical center, where the option stack starts

BUILD_SQUARE_SIZE = 36
BUILD_SQUARE_GAP = 12
AUGMENTS_TITLE_Y = 180
AUGMENTS_SUBTITLE_Y = 224
AUGMENT_SQUARES_Y = 274
TOOLTIP_PADDING = 8
TOOLTIP_MAX_WIDTH = 260

LEGEND_SWATCH_SIZE = 18
LEGEND_ROW_HEIGHT = 34


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


def animated_player_position(run: LabyrinthRun, now: float) -> tuple[float, float]:
    """
    Where to draw the player this frame, in grid-cell units (not yet scaled
    to pixels) -- run.player itself if no zip animation is in flight or it's
    already expired, otherwise linearly interpolated between the
    animation's from_cell/to_cell. Exposed as a standalone, pygame-free
    function (mirroring Layout's own pattern) so the interpolation math is
    testable without a real surface.
    """
    px, py = run.player
    anim = run.teleport_animation
    if anim is None:
        return px, py
    age = now - anim.started_at
    if age >= ZIP_ANIMATION_DURATION_SECONDS:
        return px, py
    t = max(0.0, min(1.0, age / ZIP_ANIMATION_DURATION_SECONDS))
    fx, fy = anim.from_cell
    tx, ty = anim.to_cell
    return fx + (tx - fx) * t, fy + (ty - fy) * t


class Layout:
    """Computed rects for the current cols/rows -- shared by draw() and progression/app.py::run_labyrinth()'s click handling."""

    def __init__(self, cols: int, rows: int) -> None:
        self.cell = max(1, MAZE_AREA_SIZE // max(cols, rows))
        self.maze_w = cols * self.cell
        self.maze_h = rows * self.cell
        self.window_h = MAZE_AREA_SIZE + HUD_HEIGHT
        self.window_w = SIDEBAR_W + MAZE_AREA_SIZE + SIDEBAR_W

        self.left = pygame.Rect(0, 0, SIDEBAR_W, self.window_h)
        self.maze_origin = (SIDEBAR_W, 0)
        self.hud = pygame.Rect(SIDEBAR_W, MAZE_AREA_SIZE, MAZE_AREA_SIZE, HUD_HEIGHT)
        # Legend sidebar -- always visible (not just on break screens),
        # static content, no click targets, so it doesn't interact with
        # break-card hit-testing (self.cards below, entirely within the
        # maze area) at all.
        self.right = pygame.Rect(SIDEBAR_W + MAZE_AREA_SIZE, 0, SIDEBAR_W, self.window_h)

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
        # Sized to MAX_ACTIVE_AUGMENTS fixed slots, not the full (still-growing)
        # augment catalog -- unlike perks, which show their entire static
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
            visible = run.visible_and_discovered_cells()  # None == fog of war inactive, draw everything
            self._draw_maze(run.grid, layout, visible)
            self._draw_pellets(run.pellets, layout, visible)
            self._draw_gold_pellets(run.gold_pellets, layout, visible)
            self._draw_hazards(run.hazards, layout, visible)
            self._draw_teleporters(run.teleporters, layout, visible)
            self._draw_doors_and_keys(run, layout, visible)
            self._draw_pressure_pads(run.pressure_pads, layout, visible)
            self._draw_goal(run.goal, layout, visible)
            if run.secondary_goal is not None:
                self._draw_goal(run.secondary_goal, layout, visible)  # Twin Goals -- same visual as the primary goal, either one clears the maze
            self._draw_player(run, layout)
            self._draw_popups(run, layout)

        self._draw_hud(run, layout)
        if run.rotation_warning_active:
            self._draw_rotation_warning(layout)
        self._draw_build_sidebar(run.build, layout, mouse_pos)
        self._draw_augment_sidebar(run.augment_build, layout, mouse_pos)
        self._draw_legend(layout)

        if run.failed:
            self._draw_overlay(
                f"Time's up at maze {run.maze_index}/{LABYRINTH_TOTAL_MAZES}",
                "R = Base (spend gold)     ESC = quit",
            )
        elif run.completed_run:
            self._draw_overlay(
                "All 100 mazes complete!",
                "R = Base (spend gold)     ESC = quit",
            )

    # ── Maze / entities ──────────────────────────────────────────────────

    def _draw_maze(self, grid, layout: Layout, visible: set | None = None) -> None:
        ox, oy = layout.maze_origin
        cell = layout.cell
        for row in range(len(grid)):
            for col in range(len(grid[0])):
                if visible is not None and (col, row) not in visible:
                    continue  # self.surface.fill(C_BG) already ran -- an undiscovered cell just stays background-coloured
                colour = C_WALL if grid[row][col] == 1 else C_FLOOR
                pygame.draw.rect(self.surface, colour, pygame.Rect(ox + col * cell, oy + row * cell, cell, cell))

    def _draw_goal(self, goal, layout: Layout, visible: set | None = None) -> None:
        if visible is not None and goal not in visible:
            return
        ox, oy = layout.maze_origin
        cell = layout.cell
        gx, gy = goal
        icon = sprites.get("goal", cell)
        if icon is not None:
            self.surface.blit(icon, (ox + gx * cell, oy + gy * cell))
            return
        pad = max(1, cell // 7)
        pygame.draw.ellipse(self.surface, C_GOAL, pygame.Rect(ox + gx * cell + pad, oy + gy * cell + pad, cell - 2 * pad, cell - 2 * pad))

    def _draw_player(self, run: LabyrinthRun, layout: Layout) -> None:
        ox, oy = layout.maze_origin
        cell = layout.cell
        px, py = animated_player_position(run, time.monotonic())
        icon = sprites.get("player", cell)
        if icon is not None:
            self.surface.blit(icon, (ox + px * cell, oy + py * cell))
            return
        center = (ox + px * cell + cell // 2, oy + py * cell + cell // 2)
        radius = max(1, cell // 2 - 3)
        pygame.draw.circle(self.surface, C_PLAYER, center, radius)
        draw_smiley_face(self.surface, C_BG, center, radius)

    def _draw_pellets(self, pellets, layout: Layout, visible: set | None = None) -> None:
        ox, oy = layout.maze_origin
        cell = layout.cell
        icon = sprites.get("pellet", cell)
        for pellet in pellets:
            x, y = pellet.pos
            if visible is not None and (x, y) not in visible:
                continue
            if icon is not None:
                self.surface.blit(icon, (ox + x * cell, oy + y * cell))
                continue
            r = max(1, cell // 5)
            colour = PELLET_KIND_COLOURS.get(pellet.kind, C_PELLET)
            pygame.draw.circle(self.surface, colour, (ox + x * cell + cell // 2, oy + y * cell + cell // 2), r)

    def _draw_gold_pellets(self, gold_pellets, layout: Layout, visible: set | None = None) -> None:
        ox, oy = layout.maze_origin
        cell = layout.cell
        icon = sprites.get("gold", cell)
        for gold_pellet in gold_pellets:
            x, y = gold_pellet.pos
            if visible is not None and (x, y) not in visible:
                continue
            if icon is not None:
                self.surface.blit(icon, (ox + x * cell, oy + y * cell))
                continue
            r = max(1, cell // 5)
            pygame.draw.circle(self.surface, C_GOLD, (ox + x * cell + cell // 2, oy + y * cell + cell // 2), r)

    def _draw_hazards(self, hazards, layout: Layout, visible: set | None = None) -> None:
        ox, oy = layout.maze_origin
        cell = layout.cell
        pad = max(1, cell // 5)
        icon = sprites.get("hazard", cell)
        for hazard in hazards:
            x, y = hazard.pos
            if visible is not None and (x, y) not in visible:
                continue
            if icon is not None:
                self.surface.blit(icon, (ox + x * cell, oy + y * cell))
                continue
            pygame.draw.rect(
                self.surface, C_HAZARD,
                pygame.Rect(ox + x * cell + pad, oy + y * cell + pad, cell - 2 * pad, cell - 2 * pad),
            )

    def _draw_teleporters(self, teleporters, layout: Layout, visible: set | None = None) -> None:
        ox, oy = layout.maze_origin
        cell = layout.cell
        pad = max(1, cell // 5)
        for pair in teleporters:
            colour = C_TELEPORT_PAIRS[pair.color_index % len(C_TELEPORT_PAIRS)]
            for x, y in (pair.a, pair.b):
                if visible is not None and (x, y) not in visible:
                    continue
                rect = pygame.Rect(ox + x * cell + pad, oy + y * cell + pad, cell - 2 * pad, cell - 2 * pad)
                pygame.draw.rect(self.surface, colour, rect, width=max(2, cell // 8))

    def _draw_doors_and_keys(self, run: LabyrinthRun, layout: Layout, visible: set | None = None) -> None:
        ox, oy = layout.maze_origin
        cell = layout.cell

        locked_icon = sprites.get("door_locked", cell)
        unlocked_icon = sprites.get("door_unlocked", cell)
        for pair in run.doors:
            x, y = pair.door
            if visible is not None and (x, y) not in visible:
                continue
            locked = pair.door in run._locked_doors
            icon = locked_icon if locked else unlocked_icon
            if icon is not None:
                self.surface.blit(icon, (ox + x * cell, oy + y * cell))
                continue
            pad = max(1, cell // 6)
            colour = C_DOOR_LOCKED if locked else C_DOOR_UNLOCKED
            pygame.draw.rect(
                self.surface, colour,
                pygame.Rect(ox + x * cell + pad, oy + y * cell + pad, cell - 2 * pad, cell - 2 * pad),
            )

        key_icon = sprites.get("key", cell)
        pair_colour = {pair.door: C_DOOR_KEY_PAIRS[pair.color_index % len(C_DOOR_KEY_PAIRS)] for pair in run.doors}
        for key in run.keys:
            x, y = key.pos
            if visible is not None and (x, y) not in visible:
                continue
            if key_icon is not None:
                self.surface.blit(key_icon, (ox + x * cell, oy + y * cell))
                continue
            colour = pair_colour.get(key.door_cell, C_DOOR_KEY_PAIRS[0])
            r = max(1, cell // 5)
            pygame.draw.circle(self.surface, colour, (ox + x * cell + cell // 2, oy + y * cell + cell // 2), r)

    def _draw_pressure_pads(self, pressure_pads, layout: Layout, visible: set | None = None) -> None:
        """
        The pad markers themselves -- the wall segment they control needs
        no drawing of its own: it's a plain cell in run.grid, so
        _draw_maze() already renders it correctly (wall before triggering,
        floor after) with zero special-casing.
        """
        ox, oy = layout.maze_origin
        cell = layout.cell
        pad_px = max(1, cell // 5)
        for shift_pad in pressure_pads:
            x, y = shift_pad.pad
            if visible is not None and (x, y) not in visible:
                continue
            colour = C_PRESSURE_PADS[shift_pad.color_index % len(C_PRESSURE_PADS)]
            rect = pygame.Rect(ox + x * cell + pad_px, oy + y * cell + pad_px, cell - 2 * pad_px, cell - 2 * pad_px)
            pygame.draw.rect(self.surface, colour, rect, border_radius=max(2, cell // 6))

    def _draw_popups(self, run: LabyrinthRun, layout: Layout) -> None:
        """Floating "+Xs"/"-Xs" labels for pellet/hazard/speed-bonus time changes -- rises and fades out over its lifetime."""
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

        gold_label = self.font_small.render(f"{run.gold}g", True, C_GOLD)
        self.surface.blit(gold_label, (layout.hud.right - gold_label.get_width() - 10, layout.hud.y + 8))

    def _draw_rotation_warning(self, layout: Layout) -> None:
        """A little arrow, plus label, warning the player a maze rotation is about to fire -- see run.rotation_warning_active."""
        cx = layout.hud.centerx
        cy = layout.hud.y + layout.hud.height // 2
        size = 12
        icon = sprites.get("rotate_warning", size * 2)
        if icon is not None:
            self.surface.blit(icon, (cx - size, cy - size))
        else:
            points = [(cx - size, cy - size), (cx - size, cy + size), (cx + size, cy)]
            pygame.draw.polygon(self.surface, C_ROTATE_WARNING, points)
        label = self.font_small.render("ROTATING!", True, C_ROTATE_WARNING)
        self.surface.blit(label, (cx + size + 10, cy - label.get_height() // 2))

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

    # ── Legend sidebar ──────────────────────────────────────────────────

    def _draw_legend(self, layout: Layout) -> None:
        """Static reference for every colour-coded entity currently in play -- always visible, no click targets."""
        pygame.draw.rect(self.surface, C_PANEL_BG, layout.right)
        pygame.draw.line(self.surface, C_PANEL_LINE, (layout.right.x, 0), (layout.right.x, layout.right.height), 2)

        title = self.font_big.render("LEGEND", True, C_TEXT)
        self.surface.blit(title, (layout.right.x + 16, 16))

        entries = [
            (C_PLAYER, "circle", "Player"),
            (C_GOAL, "circle", "Goal"),
            (C_PELLET, "circle", "Time Pellet"),
            (C_PELLET_DOUBLE, "circle", "Double Pellet"),
            (C_PELLET_VOLATILE, "circle", "Volatile Pellet"),
            (C_PELLET_CHAIN, "circle", "Chain Pellet"),
            (C_PELLET_FREEZE, "circle", "Freeze Pellet"),
            (C_PELLET_GAMBLE, "circle", "Gamble Pellet"),
            (C_GOLD, "circle", "Gold Pellet"),
            (C_HAZARD, "square", "Hazard"),
            (C_DOOR_LOCKED, "square", "Locked Door"),
            (C_DOOR_UNLOCKED, "square", "Unlocked Door"),
            (C_SPEED_BONUS, "square", "Speed Bonus"),
            (C_ROTATE_WARNING, "triangle", "Rotation Warning"),
            (C_PRESSURE_PADS[0], "square", "Pressure Pad"),
        ]

        x = layout.right.x + 16
        y = 56
        swatch = LEGEND_SWATCH_SIZE
        for colour, shape, label in entries:
            if shape == "circle":
                pygame.draw.circle(self.surface, colour, (x + swatch // 2, y + swatch // 2), swatch // 2)
            elif shape == "triangle":
                pygame.draw.polygon(self.surface, colour, [(x, y), (x, y + swatch), (x + swatch, y + swatch // 2)])
            else:
                pygame.draw.rect(self.surface, colour, pygame.Rect(x, y, swatch, swatch))
            self.surface.blit(self.font_small.render(label, True, C_TEXT), (x + swatch + 10, y + 1))
            y += LEGEND_ROW_HEIGHT

        y += 6
        pygame.draw.rect(self.surface, C_TELEPORT_PAIRS[0], pygame.Rect(x, y, swatch, swatch), width=3)
        self.surface.blit(self.font_small.render("Teleporter", True, C_TEXT), (x + swatch + 10, y + 1))
        self.surface.blit(self.font_small.render("(linked pads match)", True, C_DIM), (x, y + 24))
        y += LEGEND_ROW_HEIGHT + 20

        pygame.draw.circle(self.surface, C_DOOR_KEY_PAIRS[0], (x + swatch // 2, y + swatch // 2), swatch // 2)
        self.surface.blit(self.font_small.render("Key", True, C_TEXT), (x + swatch + 10, y + 1))
        self.surface.blit(self.font_small.render("(matches its own door)", True, C_DIM), (x, y + 24))

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
            surf = self.font_small.render(line, True, C_CARD_DESC)
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

            name_y = rect.y + CARD_PADDING + 28
            for line in _wrap_text(self.font_big, card.name, text_w):
                name = self.font_big.render(line, True, C_TEXT)
                self.surface.blit(name, (rect.x + CARD_PADDING, name_y))
                name_y += CARD_NAME_LINE_HEIGHT

            description = card.description
            if is_augment:
                level = run.augment_build.level_of(card.id)
                if level > 0:
                    description = f"{description} (currently level {level})"

            desc_y = name_y + 10
            for line in _wrap_text(self.font_small, description, text_w):
                desc = self.font_small.render(line, True, C_CARD_DESC)
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

    # ── Pause menu ───────────────────────────────────────────────────────

    def pause_option_rects(self) -> list[pygame.Rect]:
        """Shared by draw_pause_overlay() and app.py's click handling -- same convention as Layout.cards/menu/renderer.py's option_rects()."""
        cx = self.surface.get_width() // 2
        top = self.surface.get_height() // 2 + PAUSE_OPTION_START_Y_OFFSET
        return [
            pygame.Rect(cx - PAUSE_OPTION_W // 2, top + i * (PAUSE_OPTION_H + PAUSE_OPTION_GAP), PAUSE_OPTION_W, PAUSE_OPTION_H)
            for i in range(len(PAUSE_OPTIONS))
        ]

    def draw_pause_overlay(self, run: LabyrinthRun, menu: PauseMenu, mouse_pos: tuple[int, int], alpha: int = 255) -> None:
        """
        Draws the normal (frozen) maze scene underneath, then a black
        overlay on top -- fully opaque (alpha=255) by default, so the maze
        is completely hidden while paused, or partially see-through while
        the Peek augment's fade-in is still in progress (see
        app.py::_run_pause_loop()). One code path serves both cases rather
        than a separate "don't draw the maze at all" branch.
        """
        self.draw(run)

        overlay = pygame.Surface(self.surface.get_size(), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, alpha))
        self.surface.blit(overlay, (0, 0))

        title = self.font_huge.render("Paused", True, C_TEXT)
        cx = self.surface.get_width() // 2
        title_y = self.surface.get_height() // 2 + PAUSE_OPTION_START_Y_OFFSET - 50
        self.surface.blit(title, title.get_rect(center=(cx, title_y)))

        for i, ((_, label), rect) in enumerate(zip(PAUSE_OPTIONS, self.pause_option_rects())):
            selected = i == menu.cursor
            hovered = rect.collidepoint(mouse_pos)
            colour = C_BUTTON_HOVER if (selected or hovered) else C_BUTTON
            pygame.draw.rect(self.surface, colour, rect, border_radius=8)
            pygame.draw.rect(self.surface, C_FLASH if selected else C_DIM, rect, width=2, border_radius=8)
            text = self.font_button.render(label, True, C_TEXT)
            self.surface.blit(text, text.get_rect(center=rect.center))
