"""
renderer.py
-----------
Software raycaster for the arena interlude -- Wolfenstein-3D-style
pseudo-3D drawn with plain pygame.draw calls, no OpenGL, so it ships
through the existing pygbag web build untouched (see
docs/planning/3d-rework.md, "Engine research").

Per frame: cast one ray per screen column against the snapshotted maze
grid, draw a vertical wall strip whose height is 1/distance, shaded darker
with distance. A strip whose hit cell is on the recorded route is tinted
toward C_TRAIL so the breadcrumb to the exit stays visible in 3D. Enemies
and treasures render as flat distance-scaled billboards, depth-tested
against the wall strips.
"""

from __future__ import annotations

import math

import pygame

from maze_game.constants import (
    ARENA_WIN_W, ARENA_WIN_H, ARENA_FOV_DEG, ARENA_RAY_COUNT, ARENA_MAX_DEPTH,
    ARENA_CEILING, ARENA_FLOOR_FILL, ARENA_FOG, C_WALL, C_TRAIL, C_TEXT, C_DIM,
    C_ARENA_ENEMY, C_ARENA_TREASURE, C_ARENA_GOAL,
)
from maze_game.arena.state import ArenaState

_ANGLE_FOR_FACING = [-math.pi / 2, 0.0, math.pi / 2, math.pi]
_HALF_FOV = math.radians(ARENA_FOV_DEG) / 2
_COL_W = ARENA_WIN_W / ARENA_RAY_COUNT


def _lerp(a: tuple[int, int, int], b: tuple[int, int, int], t: float) -> tuple[int, int, int]:
    return tuple(round(a[i] + (b[i] - a[i]) * t) for i in range(3))  # type: ignore[return-value]


def _shade(colour: tuple[int, int, int], factor: float) -> tuple[int, int, int]:
    return tuple(max(0, min(255, round(c * factor))) for c in colour)  # type: ignore[return-value]


class ArenaRenderer:
    def __init__(self, surface: pygame.Surface) -> None:
        self.surface = surface
        self.font = pygame.font.Font(None, 26)
        self.big_font = pygame.font.Font(None, 64)

    @staticmethod
    def window_size() -> tuple[int, int]:
        return ARENA_WIN_W, ARENA_WIN_H

    def set_surface(self, surface: pygame.Surface) -> None:
        self.surface = surface

    def draw(self, state: ArenaState) -> None:
        self.surface.fill(ARENA_CEILING)
        pygame.draw.rect(
            self.surface, ARENA_FLOOR_FILL,
            pygame.Rect(0, ARENA_WIN_H // 2, ARENA_WIN_W, ARENA_WIN_H - ARENA_WIN_H // 2),
        )
        depth = self._draw_walls(state)
        self._draw_billboards(state, depth)
        self._draw_hud(state)
        if state.over:
            self._draw_result(state)

    # ── Walls ─────────────────────────────────────────────────────────────

    def _camera(self, state: ArenaState):
        va = _ANGLE_FOR_FACING[state.facing]
        dir_x, dir_y = math.cos(va), math.sin(va)
        plane_len = math.tan(_HALF_FOV)
        plane_x, plane_y = -dir_y * plane_len, dir_x * plane_len
        px = state.pos[0] + 0.5
        py = state.pos[1] + 0.5
        return px, py, dir_x, dir_y, plane_x, plane_y

    def _draw_walls(self, state: ArenaState) -> list[float]:
        px, py, dir_x, dir_y, plane_x, plane_y = self._camera(state)
        depth: list[float] = []
        for col in range(ARENA_RAY_COUNT):
            cam_x = 2 * col / (ARENA_RAY_COUNT - 1) - 1
            ray_x = dir_x + plane_x * cam_x
            ray_y = dir_y + plane_y * cam_x
            dist, hit_cell, side = self._cast(state, px, py, ray_x, ray_y)
            depth.append(dist)
            self._draw_strip(col, dist, hit_cell in state.trail_cells, side)
        return depth

    def _cast(self, state, px, py, ray_x, ray_y):
        map_x, map_y = int(px), int(py)
        delta_x = abs(1 / ray_x) if ray_x != 0 else 1e30
        delta_y = abs(1 / ray_y) if ray_y != 0 else 1e30
        if ray_x < 0:
            step_x, side_x = -1, (px - map_x) * delta_x
        else:
            step_x, side_x = 1, (map_x + 1 - px) * delta_x
        if ray_y < 0:
            step_y, side_y = -1, (py - map_y) * delta_y
        else:
            step_y, side_y = 1, (map_y + 1 - py) * delta_y

        side = 0
        for _ in range(ARENA_MAX_DEPTH * 2):
            if side_x < side_y:
                side_x += delta_x
                map_x += step_x
                side = 0
            else:
                side_y += delta_y
                map_y += step_y
                side = 1
            if not (0 <= map_x < state.cols and 0 <= map_y < state.rows):
                break
            if state.grid[map_y][map_x] == 1:
                if side == 0:
                    dist = (map_x - px + (1 - step_x) / 2) / ray_x
                else:
                    dist = (map_y - py + (1 - step_y) / 2) / ray_y
                return max(dist, 1e-4), (map_x, map_y), side
        return float(ARENA_MAX_DEPTH), (map_x, map_y), side

    def _draw_strip(self, col: int, dist: float, on_trail: bool, side: int) -> None:
        fog_t = min(1.0, dist / ARENA_MAX_DEPTH)
        base = _lerp(C_WALL, C_TRAIL, 0.6) if on_trail else C_WALL
        colour = _lerp(_shade(base, 0.85 if side else 1.0), ARENA_FOG, fog_t)
        line_h = min(ARENA_WIN_H * 4, int(ARENA_WIN_H / dist))
        top = ARENA_WIN_H // 2 - line_h // 2
        x0 = int(col * _COL_W)
        w = max(1, int((col + 1) * _COL_W) - x0)
        pygame.draw.rect(self.surface, colour, pygame.Rect(x0, top, w, line_h))

    # ── Billboards (enemies + treasures + the goal marker) ────────────────

    def _draw_billboards(self, state: ArenaState, depth: list[float]) -> None:
        px, py, dir_x, dir_y, plane_x, plane_y = self._camera(state)
        sprites: list[tuple[float, tuple[int, int], tuple[int, int, int], float]] = []
        for enemy in state.enemies:
            if enemy.alive:
                sprites.append((0.0, enemy.pos, C_ARENA_ENEMY, 0.8))
        for treasure in state.treasures:
            if not treasure.collected:
                sprites.append((0.0, treasure.pos, C_ARENA_TREASURE, 0.5))
        sprites.append((0.0, state.goal, C_ARENA_GOAL, 1.0))

        det = plane_x * dir_y - dir_x * plane_y
        if abs(det) < 1e-9:
            return
        inv_det = 1 / det
        projected = []
        for _, cell, colour, scale in sprites:
            rel_x = cell[0] + 0.5 - px
            rel_y = cell[1] + 0.5 - py
            tx = inv_det * (dir_y * rel_x - dir_x * rel_y)
            ty = inv_det * (-plane_y * rel_x + plane_x * rel_y)
            if ty <= 0.15:
                continue
            projected.append((ty, tx, colour, scale))
        projected.sort(reverse=True)

        for ty, tx, colour, scale in projected:
            screen_x = int((ARENA_WIN_W / 2) * (1 + tx / ty))
            size = int(abs(ARENA_WIN_H / ty) * scale)
            if size < 2:
                continue
            col_idx = min(ARENA_RAY_COUNT - 1, max(0, int(screen_x / _COL_W)))
            if ty >= depth[col_idx]:
                continue
            fog_t = min(1.0, ty / ARENA_MAX_DEPTH)
            shaded = _lerp(colour, ARENA_FOG, fog_t)
            rect = pygame.Rect(0, 0, max(2, size // 2), size)
            rect.center = (screen_x, ARENA_WIN_H // 2 + size // 6)
            pygame.draw.rect(self.surface, shaded, rect, border_radius=max(1, size // 8))

    # ── HUD ───────────────────────────────────────────────────────────────

    def _draw_hud(self, state: ArenaState) -> None:
        for i in range(state.max_health):
            colour = C_ARENA_ENEMY if i < state.health else C_DIM
            pygame.draw.circle(self.surface, colour, (24 + i * 26, 26), 9)

        remaining = max(0.0, state.time.amount)
        frac = remaining / state.time_budget if state.time_budget else 0
        bar = pygame.Rect(ARENA_WIN_W - 214, 18, 196, 16)
        pygame.draw.rect(self.surface, C_DIM, bar, 1)
        pygame.draw.rect(
            self.surface, C_ARENA_TREASURE,
            pygame.Rect(bar.x + 1, bar.y + 1, int((bar.w - 2) * frac), bar.h - 2),
        )
        self._text(f"{remaining:4.0f}s", (bar.x - 52, bar.y - 2))

        got = sum(1 for t in state.treasures if t.collected)
        self._text(f"Treasure {got}/{len(state.treasures)}", (20, ARENA_WIN_H - 30))

        if state.enemy_ahead() is not None:
            self._text("SPACE to strike", (ARENA_WIN_W // 2 - 66, ARENA_WIN_H - 44), C_ARENA_ENEMY)
        pygame.draw.circle(self.surface, C_TEXT, (ARENA_WIN_W // 2, ARENA_WIN_H // 2), 3, 1)

    def _draw_result(self, state: ArenaState) -> None:
        overlay = pygame.Surface((ARENA_WIN_W, ARENA_WIN_H), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 150))
        self.surface.blit(overlay, (0, 0))
        msg = {
            "win": "You found the exit",
            "lose": "Overwhelmed",
            "timeout": "Out of time",
            "quit": "Left the arena",
        }.get(state.outcome, "")
        label = self.big_font.render(msg, True, C_TEXT)
        self.surface.blit(label, label.get_rect(center=(ARENA_WIN_W // 2, ARENA_WIN_H // 2 - 20)))
        gold = state.gold_collected
        sub = f"+{gold} gold from treasure  --  press any key" if gold else "press any key"
        self._text(sub, None, center=(ARENA_WIN_W // 2, ARENA_WIN_H // 2 + 30))

    def _text(self, text, topleft, colour=C_TEXT, center=None) -> None:
        surf = self.font.render(text, True, colour)
        if center is not None:
            self.surface.blit(surf, surf.get_rect(center=center))
        else:
            self.surface.blit(surf, topleft)
