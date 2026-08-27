"""
bench_arena_raycast.py
----------------------
Frame-time harness for the arena interlude's per-column software raycaster
(maze_game/arena/renderer.py). Phase 6 of docs/planning/3d-rework.md asks
for a real frame-rate check of that loop in the pygbag/WASM runtime before
trusting ARENA_RAY_COUNT.

A true in-browser measurement needs an actual `pygbag --build` + a browser
with a canvas, which can't run in a headless/unattended shell. This script
is the reproducible desktop proxy: it times a full `ArenaRenderer.draw()`
(ceiling/floor fill + ARENA_RAY_COUNT wall strips + billboards + HUD) over
many frames with the camera swept through every open cell and facing, then
projects that onto the WASM runtime with a slowdown band.

The projection band (PYODIDE_SLOWDOWN_LO/HI) is deliberately pessimistic:
pure-Python loop bodies under Pyodide/WASM commonly run 3-8x slower than
desktop CPython, and the per-column loop here is exactly that shape (a
Python-level DDA cast + a pygame.draw.rect boundary crossing per column).
pygame-ce's C draw calls fare better than the loop overhead, so the real
figure usually lands nearer the low end -- but tuning the ray count off
the high end keeps a safety margin for slower phones.

Usage:
    python tools/bench_arena_raycast.py            # report at the shipped ray count
    python tools/bench_arena_raycast.py --sweep    # also sweep candidate ray counts
    python tools/bench_arena_raycast.py --frames 400

Exit code is non-zero if the projected worst-case (HI slowdown) 3D frame
time blows the 60fps budget at the shipped ARENA_RAY_COUNT, so this can
double as a cheap regression guard.
"""

from __future__ import annotations

import argparse
import os
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pygame

from maze_game import constants
from maze_game.maze import generate_maze, farthest_reachable_cell, shortest_path
from maze_game.arena.state import ArenaState, FACINGS
from maze_game.progression.run import FirstMazeRecord

PYODIDE_SLOWDOWN_LO = 3.0
PYODIDE_SLOWDOWN_HI = 8.0
BUDGET_60 = 1000.0 / 60.0
BUDGET_30 = 1000.0 / 30.0


def _make_state(dim: int, seed: int) -> ArenaState:
    import random

    rng = random.Random(seed)
    grid = generate_maze(dim, dim, rng=rng)
    start = (1, 1)
    goal = farthest_reachable_cell(grid, start)
    trail = shortest_path(grid, start, goal) or [start]
    record = FirstMazeRecord(grid=[r[:] for r in grid], goal=goal, trail=list(trail), start=start)
    return ArenaState(
        record=record, rng=rng, time_budget=90.0, max_health=3,
        enemy_count=constants.ARENA_ENEMY_COUNT,
        treasure_count=constants.ARENA_TREASURE_COUNT,
        treasure_gold=constants.ARENA_TREASURE_GOLD,
    )


def _open_cells(state: ArenaState) -> list[tuple[int, int]]:
    return [
        (x, y)
        for y in range(state.rows)
        for x in range(state.cols)
        if state.grid[y][x] == 0
    ]


def _time_draw(ray_count: int, state: ArenaState, frames: int) -> list[float]:
    # ARENA_RAY_COUNT is read at module import in renderer.py (_COL_W etc.),
    # so patch + reimport to measure a candidate count cleanly.
    constants.ARENA_RAY_COUNT = ray_count
    import importlib

    from maze_game.arena import renderer as renderer_mod

    importlib.reload(renderer_mod)
    pygame.font.init()
    surface = pygame.Surface(renderer_mod.ArenaRenderer.window_size())
    renderer = renderer_mod.ArenaRenderer(surface)

    cells = _open_cells(state)
    samples: list[float] = []
    i = 0
    while len(samples) < frames:
        state.pos = cells[i % len(cells)]
        state.facing = FACINGS.index(FACINGS[i % len(FACINGS)])
        i += 1
        t0 = time.perf_counter()
        renderer.draw(state)
        samples.append((time.perf_counter() - t0) * 1000.0)
    return samples


def _report(label: str, samples: list[float]) -> float:
    samples_sorted = sorted(samples)
    mean = statistics.fmean(samples)
    p95 = samples_sorted[int(len(samples_sorted) * 0.95)]
    worst = samples_sorted[-1]
    proj_lo = p95 * PYODIDE_SLOWDOWN_LO
    proj_hi = p95 * PYODIDE_SLOWDOWN_HI
    print(
        f"{label:>22}: desktop mean {mean:6.3f}ms  p95 {p95:6.3f}ms  max {worst:6.3f}ms"
        f"   -> WASM p95 ~{proj_lo:6.2f}-{proj_hi:6.2f}ms"
        f"   ({BUDGET_60/proj_hi:4.1f}-{BUDGET_60/proj_lo:4.1f}x 60fps budget)"
    )
    return proj_hi


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--frames", type=int, default=300)
    ap.add_argument("--dim", type=int, default=9, help="maze size (arena replays maze 1 == MIN_DIMENSION)")
    ap.add_argument("--sweep", action="store_true")
    args = ap.parse_args()

    shipped = constants.ARENA_RAY_COUNT
    state = _make_state(args.dim, seed=1)

    print(
        f"arena raycast frame-time proxy -- {args.dim}x{args.dim} maze, "
        f"{constants.ARENA_WIN_W}x{constants.ARENA_WIN_H}, {args.frames} frames/config"
    )
    print(
        f"60fps budget {BUDGET_60:.2f}ms | 30fps budget {BUDGET_30:.2f}ms | "
        f"WASM slowdown band {PYODIDE_SLOWDOWN_LO:g}-{PYODIDE_SLOWDOWN_HI:g}x\n"
    )

    counts = [120, 160, 200, 240, 320] if args.sweep else [shipped]
    proj_hi_at_shipped = None
    for rc in counts:
        proj = _report(f"{rc} rays" + ("  (shipped)" if rc == shipped else ""), _time_draw(rc, state, args.frames))
        if rc == shipped:
            proj_hi_at_shipped = proj

    constants.ARENA_RAY_COUNT = shipped  # leave the module as we found it
    print()
    if proj_hi_at_shipped is None:
        return 0
    if proj_hi_at_shipped > BUDGET_60:
        print(
            f"FAIL: projected worst-case WASM frame ~{proj_hi_at_shipped:.1f}ms at "
            f"ARENA_RAY_COUNT={shipped} exceeds the {BUDGET_60:.1f}ms 60fps budget."
        )
        return 1
    print(
        f"OK: projected worst-case WASM frame ~{proj_hi_at_shipped:.1f}ms at "
        f"ARENA_RAY_COUNT={shipped} fits the 60fps budget."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
