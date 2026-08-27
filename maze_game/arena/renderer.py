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
    ARENA_CEILING, ARENA_FLOOR_FILL, ARENA_FOG, ARENA_MOVE_SMOOTH, ARENA_TURN_SMOOTH,
    C_WALL, C_TRAIL, C_TEXT, C_DIM,
    C_ARENA_ENEMY, C_ARENA_TREASURE, C_ARENA_GOAL,
)
from maze_game.arena.state import ArenaState
from maze_game.arena.entities import draw_enemy, draw_treasure, draw_goal

_ANGLE_FOR_FACING = [-math.pi / 2, 0.0, math.pi / 2, math.pi]
_HALF_FOV = math.radians(ARENA_FOV_DEG) / 2
_COL_W = ARENA_WIN_W / ARENA_RAY_COUNT
_TWO_PI = 2 * math.pi


def _lerp(a: tuple[int, int, int], b: tuple[int, int, int], t: float) -> tuple[int, int, int]:
    return tuple(round(a[i] + (b[i] - a[i]) * t) for i in range(3))  # type: ignore[return-value]


def _shade(colour: tuple[int, int, int], factor: float) -> tuple[int, int, int]:
    return tuple(max(0, min(255, round(c * factor))) for c in colour)  # type: ignore[return-value]


class ArenaRenderer:
    def __init__(self, surface: pygame.Surface) -> None:
        self.surface = surface
        self.font = pygame.font.Font(None, 26)
        self.big_font = pygame.font.Font(None, 64)
        # Interpolated camera pose -- eases toward the discrete tile
        # position/facing each frame so tank steps and 90-degree turns read
        # as smooth motion (the sim underneath stays strictly grid-based).
        self._vx: float | None = None
        self._vy = 0.0
        self._va = 0.0

    @staticmethod
    def window_size() -> tuple[int, int]:
        return ARENA_WIN_W, ARENA_WIN_H

    def set_surface(self, surface: pygame.Surface) -> None:
        self.surface = surface

    def draw(self, state: ArenaState, intro: bool = False) -> None:
        self._update_view(state)
        self.surface.fill(ARENA_CEILING)
        pygame.draw.rect(
            self.surface, ARENA_FLOOR_FILL,
            pygame.Rect(0, ARENA_WIN_H // 2, ARENA_WIN_W, ARENA_WIN_H - ARENA_WIN_H // 2),
        )
        depth = self._draw_walls(state)
        self._draw_billboards(state, depth)
        self._draw_hud(state)
        if intro:
            self._draw_intro(state)
        elif state.over:
            self._draw_result(state)

    # ── Camera interpolation ─────────────────────────────────────────────

    def _update_view(self, state: ArenaState) -> None:
        tx, ty = state.pos[0] + 0.5, state.pos[1] + 0.5
        ta = _ANGLE_FOR_FACING[state.facing]
        if self._vx is None:
            self._vx, self._vy, self._va = tx, ty, ta
            return
        # A jump of more than ~1 cell isn't a step (teleport / test warp) --
        # snap rather than gliding through walls.
        if math.hypot(tx - self._vx, ty - self._vy) > 1.6:
            self._vx, self._vy = tx, ty
        else:
            self._vx += (tx - self._vx) * ARENA_MOVE_SMOOTH
            self._vy += (ty - self._vy) * ARENA_MOVE_SMOOTH
        d_ang = (ta - self._va + math.pi) % _TWO_PI - math.pi
        self._va += d_ang * ARENA_TURN_SMOOTH

    # ── Walls ─────────────────────────────────────────────────────────────

    def _camera(self, state: ArenaState):
        va = self._va
        dir_x, dir_y = math.cos(va), math.sin(va)
        plane_len = math.tan(_HALF_FOV)
        plane_x, plane_y = -dir_y * plane_len, dir_x * plane_len
        px = self._vx if self._vx is not None else state.pos[0] + 0.5
        py = self._vy
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

    def _sprite_list(self, state: ArenaState):
        """(cell, base_colour, width_scale, height_scale, painter) per visible entity."""
        out = []
        for enemy in state.enemies:
            if enemy.alive:
                out.append((
                    enemy.pos, enemy.kind.colour, 0.62, enemy.kind.height,
                    lambda s, r, tint, k=enemy.kind: draw_enemy(s, r, k, tint),
                ))
        for treasure in state.treasures:
            if not treasure.collected:
                out.append((treasure.pos, C_ARENA_TREASURE, 0.55, 0.5, draw_treasure))
        out.append((state.goal, C_ARENA_GOAL, 0.9, 0.95, draw_goal))
        return out

    def _draw_billboards(self, state: ArenaState, depth: list[float]) -> None:
        px, py, dir_x, dir_y, plane_x, plane_y = self._camera(state)
        det = plane_x * dir_y - dir_x * plane_y
        if abs(det) < 1e-9:
            return
        inv_det = 1 / det
        projected = []
        for cell, colour, w_scale, h_scale, painter in self._sprite_list(state):
            rel_x = cell[0] + 0.5 - px
            rel_y = cell[1] + 0.5 - py
            tx = inv_det * (dir_y * rel_x - dir_x * rel_y)
            ty = inv_det * (-plane_y * rel_x + plane_x * rel_y)
            if ty <= 0.15:
                continue
            projected.append((ty, tx, colour, w_scale, h_scale, painter))
        projected.sort(reverse=True)

        for ty, tx, colour, w_scale, h_scale, painter in projected:
            screen_x = int((ARENA_WIN_W / 2) * (1 + tx / ty))
            full = abs(ARENA_WIN_H / ty)
            h = int(full * h_scale)
            w = int(full * w_scale)
            if h < 2 or w < 1:
                continue
            col_idx = min(ARENA_RAY_COUNT - 1, max(0, int(screen_x / _COL_W)))
            if ty >= depth[col_idx]:
                continue
            fog_t = min(1.0, ty / ARENA_MAX_DEPTH)
            tint = _lerp(colour, ARENA_FOG, fog_t)
            rect = pygame.Rect(0, 0, w, h)
            rect.center = (screen_x, ARENA_WIN_H // 2 + h // 6)
            painter(self.surface, rect, tint)

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

    def _draw_intro(self, state: ArenaState) -> None:
        overlay = pygame.Surface((ARENA_WIN_W, ARENA_WIN_H), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 175))
        self.surface.blit(overlay, (0, 0))
        cx = ARENA_WIN_W // 2
        title = self.big_font.render("MAZE I  --  REPLAY", True, C_TEXT)
        self.surface.blit(title, title.get_rect(center=(cx, ARENA_WIN_H // 2 - 96)))
        lines = [
            "You cleared the first five. Now walk your very first maze back --",
            "this time from the inside, in the dark, with company.",
            "",
            "Arrows / WASD  move and turn      SPACE  strike what blocks the way",
            "Follow the pale trail to the exit.  Side dead-ends hide treasure.",
            "",
            "press any key",
        ]
        y = ARENA_WIN_H // 2 - 34
        for line in lines:
            colour = C_DIM if line == "press any key" else C_TEXT
            self._text(line, None, colour=colour, center=(cx, y))
            y += 30

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
