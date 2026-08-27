# 3D Rework: Trail + Maze-1 Arena Replay

Design doc for a major addition: keep the existing 2D maze-completing
gameplay for the first 5 mazes of a Labyrinth Run, but after clearing the
5th, drop the player into a 3D ("2.5D") replay of the very first maze they
solved -- walls/floor from that same layout, their earlier route from it
visible as a colour trail, obstacles/enemies to fight through, and
optional treasures at the far ends of dead-end branches that cost time (and
trail readability) to detour for.

This is explicitly a multi-session effort. This document covers the engine
research (do first, before any code) and the target architecture; the
"Phased plan" section at the end tracks what's actually landed vs. still
backlog.

## Open questions worth confirming before Phase 2 (see "Phased plan")

This doc makes a few concrete calls where the original ask was ambiguous.
Flagging them here rather than guessing silently:

1. **Scope of "the first 5 mazes"**: assumed to be Labyrinth Run's existing
   `LABYRINTH_GROUP_SIZE` (5) cadence -- i.e. the arena is a new *one-time*
   break inserted right after the very first group's shop/augment breaks,
   not a new standalone mode and not something that repeats every group.
   Freeplay is untouched (no "5 mazes" concept exists there).
2. **Combat depth**: assumed a minimal first pass -- contact-based
   hazards plus one deliberate "attack" action (see "Enemies/obstacles"
   below), not aiming/projectiles -- to keep the control surface as small
   as the rest of the game (arrows + one action key). Escalate later if it
   feels too thin once it's actually playable.
3. **Movement feel in the arena**: assumed tile-based "tank" controls
   (rotate in place, move one cell at a time) rather than free continuous
   FPS movement, for the same "simple/placeholder is fine for a first
   pass" reason, and because it reuses the maze grid's wall collision
   exactly as-is (no new collision geometry).

## Engine research: can pygame + pygbag do 3D?

**Recommendation: yes, via a software raycaster (Wolfenstein-3D-style
pseudo-3D) drawn with plain `pygame.draw`/`Surface` calls -- no OpenGL, no
engine swap, no change to `deploy_web.py` or the pygbag build step.**

### Why not real hardware 3D (OpenGL/WebGL) from Python here

`deploy_web.py` builds this game with **pygbag**, which packages
**pygame-ce** compiled to WebAssembly via Emscripten, running on top of
Pyodide/SDL2-in-the-browser. The existing 2D game already proves that
`pygame.Surface`/`pygame.draw`/`blit` work fine through this pipeline --
that's the entire rendering surface it uses today.

Actual hardware-accelerated 3D from Python (`PyOpenGL`, `moderngl`, etc.)
binds to a native `libGL` via `ctypes`. There is no native GL driver to
bind to inside a WASM sandbox -- these bindings do not have a supported,
stable path under Pyodide/Emscripten. `pygame.display.set_mode(...,
OPENGL)` itself is an SDL-level GL context request that *can* map to
WebGL through Emscripten's SDL2 port in principle, but the Python-side
binding needed to actually issue draw calls against it is the missing
piece, and isn't something pygbag ships or tests against. Betting the
whole feature on this working reliably in a shipped browser build would be
high risk for very little payoff, given the ask explicitly allows
"simple/placeholder 3D."

*(Caveat on how this conclusion was reached: this is based on the
documented architecture of pygame-ce/pygbag/Pyodide -- Emscripten-compiled
SDL2, no ctypes-based native GL passthrough -- not a live web search;
interactive approval for the web-search tool wasn't obtainable in this
unattended session. If there's any appetite to double-check, a ~10-minute
spike next session -- try `pygame.display.set_mode(flags=OPENGL)` plus a
trivial `moderngl` triangle under an actual `pygbag --build`, not just
desktop pygame -- would confirm or kill it fast. Nothing below depends on
that answer either way, so it's safe to build the raycaster path now
regardless.)*

### Why not a different engine/framework

A real 3D engine with genuine WebGL/WebGPU support (Three.js, Babylon.js,
PlayCanvas, or another engine's own HTML5/web export such as Godot) can
absolutely render proper 3D in a browser. But every one of those is a
different language/runtime (JS, or a different engine's own scripting and
build system) with its own build pipeline (Node/bundler, or that engine's
own web-export tooling) -- adopting one means either rewriting the game
outright or bolting a second toolchain onto this repo alongside pygbag.
That fails the "deployable the same way" requirement outright, and is a
far bigger rewrite than a maze game with placeholder 3D warrants.
Panda3D/Ursina (a common "easy 3D in Python" answer) has no browser export
target at all -- not viable regardless of deploy constraints.

### The chosen approach: raycasting

A classic Wolfenstein-3D-style raycaster is the standard technique for
exactly this game's shape -- a grid-based maze with square cells, walls at
fixed positions, viewed from inside one cell facing one of 4-8 directions.
Per frame: cast one ray per screen column against the same wall/passage
grid `generate_maze()` already produces, find the distance to the nearest
wall hit, draw a vertical strip whose height is inversely proportional to
that distance (closer = taller), shaded darker with distance for a cheap
depth cue. Enemies/treasures render as flat "billboard" rects scaled by
their distance from the player, sorted back-to-front. All of this is
`pygame.draw.line`/`pygame.draw.rect` calls into a `Surface` -- exactly
the API pygbag already ships -- so **no change to `deploy_web.py`,
`requirements.txt`, or the build step is needed.** It's also cheap enough
(one distance calc per screen column, a few hundred at most) to comfortably
hit 60fps even in a WASM runtime; can downscale the column count if a
future pygbag build proves otherwise.

## Data model: the trail

**Status: implemented this session.** `LabyrinthRun.trail` (in
`progression/run.py`) is a `list[tuple[int, int]]` recording every cell
the player enters, in visit order, including duplicates on backtracking
(so a corridor walked back and forth shows exactly what happened, not a
deduplicated shortest-looking path). It resets to `[START_POS]` at the
start of every maze (`_begin_maze()`) and is appended to on every
`move()`. `progression/renderer.py::_draw_trail` draws it as a thin
polyline (`pygame.draw.lines`, width = `cell // TRAIL_WIDTH_FRACTION`)
through each visited cell's centre, under every entity/the player but over
the floor/walls, so it never occludes anything and re-walking the same
ground doesn't add visual clutter beyond the line already there.

This is genuinely useful standalone in the 2D game (the original ask: "a
thin streak/trail of color behind" while solving), and is exactly the data
the arena replay needs later -- no rework required to reuse it, just a
snapshot before it's overwritten (see Phase 2 below).

## Game flow integration

Labyrinth Run already has a "stack of breaks after a maze clears" pattern
(`run.py`'s `break_kind`, `_pending_breaks`, `_breaks_due_after()`,
`_resume_after_break()`) used for the shop and augment-choice screens.
The arena slots into the same machinery as a new, *one-time* break kind:

- `_breaks_due_after(completed_index)` gains a case: when
  `completed_index == LABYRINTH_GROUP_SIZE` (5) and the arena hasn't
  fired yet this run (a new `self._arena_shown` flag, set the first time
  it queues), prepend `"arena"` to the returned list -- ahead of
  `"shop"`, so the breaks still stack in a sensible order (arena, then
  the group's shop pick, then maze 6 begins).
- Because the arena is a full alternate rendering/control mode rather
  than a card-pick overlay, `run.break_kind == "arena"` should hand off
  to a dedicated loop (`arena/app.py::run_arena()`) from
  `progression/app.py::run_labyrinth()`, the same way `main.py` already
  composes `run_base()`/`run_labyrinth()`/`run_freeplay()` as separate
  loops rather than one mega-loop. On the arena's own win/lose/quit, call
  back into `run._resume_after_break()` (or a thin
  `run.finish_arena(outcome)` wrapper around it) to continue the same
  break-stacking sequence.
- Needed alongside this: capture a `first_maze_record` (grid + goal +
  trail + start, as a small dataclass) at the moment maze 1 is cleared --
  *before* `_begin_maze()` overwrites `self.grid`/`self.trail` for maze
  2. This is the snapshot the arena renders against.

## Directory layout (and a required prerequisite reorg)

Per this project's convention, `maze_game/` is capped at 4 files + 4
subdirectories. It's currently exactly at that cap:
`constants.py`, `__init__.py`, `maze.py`, `player.py` (4 files) +
`freeplay/`, `media/`, `menu/`, `progression/` (4 dirs). Adding a 5th
directory for the new mode isn't allowed as-is -- `progression/` is
*also* already at its own 4+4 cap, so the new mode can't be nested inside
it either.

**Fix (prerequisite step, no behaviour change):** group `media/` and
`menu/` -- both small, presentation-only packages, neither core gameplay
logic nor a game "mode" in their own right -- under a new
`maze_game/presentation/` package: `presentation/media/`,
`presentation/menu/`. This frees one directory slot at the `maze_game/`
level. It's a pure move + import-path update (`from maze_game.media import
...` / `from maze_game.menu import ...`, across `progression/`,
`freeplay/`, `main.py`, and every test file that imports either) -- land
it as its own commit before adding any new code, so it's trivially
reviewable as "just a move."

**New package: `maze_game/arena/`** (the 3D replay mode), following the
same `{app.py, <state>.py, renderer.py}` split every other mode already
uses (`progression/{app,run,renderer}.py`, `freeplay/{app,game,renderer}.py`):

- `arena/state.py` -- pure state machine: player position/facing, health
  or time budget, enemy positions/state, treasure positions/collected,
  win/lose condition. Independent of pygame, same "testable without a
  display" rule `run.py`'s docstring already calls out for this codebase.
- `arena/renderer.py` -- the raycaster: casts rays against the snapshotted
  grid, shades by distance, tints any wall/floor strip whose hit cell is
  in the snapshotted trail with `C_TRAIL` (new constant, already added
  for the 2D trail -- reused as-is here) so the breadcrumb stays legible
  in 3D, draws enemy/treasure billboards as flat scaled rects (no textures
  needed for a first pass).
- `arena/app.py` -- the pygame event loop, mirroring
  `progression/app.py::run_labyrinth()`'s shape (event pump, `state.update()`,
  `renderer.draw()`, `clock.tick(FPS)`).

That's 3 files, leaving one slot free inside `arena/` for a natural 4th
(e.g. `arena/entities.py` for enemy/treasure definitions) before this
package itself would need any internal grouping.

`maze_game/` after both changes: `constants.py`, `__init__.py`, `maze.py`,
`player.py` (4 files) + `freeplay/`, `progression/`, `presentation/`,
`arena/` (4 dirs) -- back at exactly 8, the cap.

## Movement & controls in the arena

Tile-based "tank" controls, matching this game's existing "no analog
input" identity: left/right arrow rotates 90° in place, up/down moves one
cell forward/back in the current facing direction if that cell is open in
the snapshotted grid (blocked exactly like the 2D wall grid already
blocks `slide_path()` -- no separate collision geometry to write). Smooth
continuous turning/movement, if wanted later, is purely a rendering-side
interpolation on top of this same discrete state -- doesn't change
`arena/state.py`'s model.

## Enemies/obstacles ("fight through")

First pass: enemies are simple contact hazards (stationary or
short-patrol), resolved the same way `progression/entities/hazards.py`'s
`resolve_contacts()` already resolves 2D hazard contact -- touching one
costs health/time. A single deliberate action key (e.g. `SPACE`, when
facing/adjacent to an enemy, on a short cooldown) clears it, giving the
"fight through" framing without adding aiming or projectiles -- the
control surface stays arrows + one action key, the same shape as the
existing hold-`SPACE` "run to the wall" combo in the 2D game.

## Treasures

Placed at the maze's farthest-reachable dead-end branches, reusing
`maze.farthest_reachable_cell()`/`shortest_path()` -- the same primitives
that already place the 2D goal as far from the start as BFS allows.
Collecting one costs real time (same "time is the resource that matters"
framing the rest of the game already uses). Deliberately no separate
"readability penalty" mechanic is needed: because the trail overlay draws
every visited cell in one continuous colour, a detour to fetch a treasure
naturally adds extra trail segments that cross/thicken the route right at
the point of the detour -- the existing trail rendering already makes
"which way is the exit" harder to read there, for free.

## Phased plan across sessions

- **Phase 1 (this session) -- DONE.** Engine research (this doc).
  `LabyrinthRun.trail` recording + `_draw_trail()` 2D rendering, tested
  (`tests/progression/test_run.py`), manually smoke-tested against a real
  `Renderer.draw()` call.
- **Phase 2 -- DONE.** `presentation/` reorg (media/ + menu/ grouped under
  `maze_game/presentation/`, pure move + import update, its own commit).
  `FirstMazeRecord` snapshot captured in `run.py::_advance()` the moment
  maze 1 clears. One-time `"arena"` break wired in: `_advance()` prepends
  `"arena"` to the break queue at the first group boundary (guarded by
  `self._arena_shown`), `_resume_after_break()` sets `break_kind` without a
  card offer, `finish_arena()` banks treasure gold and resumes the queue.
  `choose_break_card()` treats `"arena"` as skip, so headless full-run
  tests don't hang on it.
- **Phase 3 -- DONE.** `maze_game/arena/` package:
  - `state.py` -- pure tile-based state machine (turn / step / attack /
    update), wall collision straight off the snapshotted grid, win on
    reaching the goal cell, timeout on the time budget.
  - `renderer.py` -- DDA software raycaster: one wall-distance calc per of
    `ARENA_RAY_COUNT` columns, distance + side shading, strips whose hit
    cell is on the recorded route tinted toward `C_TRAIL`, enemy/treasure/
    goal billboards depth-tested against the wall strips. Plain
    `pygame.draw` only -- no engine/deploy change.
  - `app.py` -- the event loop (arrows/WASD + SPACE), `run_arena()` entry
    point that `progression/app.py` hands off to.
- **Phase 4 -- DONE (first pass).** Enemies spawn along the recorded route
  (`state._place_enemies`), block movement, wake and greedily chase within
  range, strike every other tick while adjacent; `attack()` clears the one
  directly ahead. Health 0 -> `"lose"`.
- **Phase 5 -- DONE (first pass).** Treasures spawn at the farthest
  dead-ends off the route (`state._place_treasures`); walking onto one
  banks `ARENA_TREASURE_GOLD`, paid out via `finish_arena()`. The detour
  cost is the ticking time budget + the extra trail scribble in the replay
  (no separate readability-penalty mechanic needed -- see "Treasures").
- **Backlog / polish.** Smooth turn+move interpolation on top of the
  discrete state; textured or sprite billboards instead of flat rects;
  enemy variety; a proper arena intro screen; tuning pass on
  `ARENA_*` constants once it's been playtested in a real web build.
- **Phase 6 -- DONE (proxy; true in-browser check still open).**
  `tools/bench_arena_raycast.py` times a full `ArenaRenderer.draw()`
  (ceiling/floor fill + N wall strips + billboards + HUD) over hundreds of
  frames with the camera swept through every open cell/facing, then
  projects onto the WASM runtime with a pessimistic 3-8x slowdown band.
  At the old `ARENA_RAY_COUNT = 240` the worst-case projection sat at
  ~16ms -- right on the 60fps edge with no room for enemy AI, the event
  pump, the pygbag main-loop overhead, or slower phones. **Downscaled to
  160** (~6px/column, still fine for placeholder pseudo-3D): worst-case
  projection ~13ms, comfortable headroom.
  - `deploy_web.py` lives only on the unmerged `web-wasm-port` branch, and
    a genuine `pygbag --build` + in-browser FPS trace needs a browser with
    a canvas -- not runnable in a headless/unattended shell. The bench
    script is the reproducible harness for whoever runs that check on a
    real build; if it disagrees, drop the ray count further (the sweep
    shows 120 rays projects at ~11ms worst-case).
  - The OpenGL caveat (top of this doc) is untouched -- still worth the
    ~10-min spike next time someone has a live `pygbag --build` open.
