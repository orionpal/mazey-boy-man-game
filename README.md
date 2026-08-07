# Maze Game

A minimal, keyboard-driven maze game built with Python and pygame.

`main.py` opens to a menu with two modes. **Labyrinth Run** is the main
experience: 100 mazes, gradually growing in size, sharing one time budget
for the whole run. Press an arrow key and your dot slides in that direction
until it hits a wall or reaches a junction — then you choose again.
**Relax (Free Play)** is a single maze at a time, adjustable size, no
timer, with a run-history log — for practicing, or just wandering without
pressure (also runnable directly via `mvp_main.py`, skipping the menu).

---

## Getting Started

### Prerequisites

- Python 3.11 or newer ([python.org](https://www.python.org/downloads/))
- pip (bundled with Python)

### 1. Clone the repository

```bash
git clone https://github.com/your-username/maze-game.git
cd maze-game
```

### 2. Create a virtual environment (recommended)

```bash
python -m venv .venv
```

Activate it:

| Platform | Command |
|----------|---------|
| macOS / Linux | `source .venv/bin/activate` |
| Windows (cmd) | `.venv\Scripts\activate.bat` |
| Windows (PowerShell) | `.venv\Scripts\Activate.ps1` |

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Run the game

```bash
python main.py      # opens a menu: Labyrinth Run (timed, see docs/progression.md) or Relax (free play, no timer)
python mvp_main.py  # skips the menu, straight into Relax/free play
```

---

## Building a Standalone Executable

No need to have Python/pip installed to just play it — [PyInstaller](https://pyinstaller.org/) bundles the interpreter, pygame, and the game into one file:

```bash
pip install pyinstaller
pyinstaller --onefile --name maze-game --add-data "assets:assets" main.py
```

(Swap `main.py` for `mvp_main.py` in that command to package free-play mode instead.)

The executable lands in `dist/maze-game` (`dist/maze-game.exe` on Windows) — a
single ~16MB file with no dependencies to install; just double-click it (or
run it) to play. A couple of things worth knowing:

- **Not cross-platform to build**: PyInstaller packages for whatever OS you
  run it *on* — build on Windows for a `.exe`, macOS for a Mac app, Linux for
  an ELF binary. There's no cross-compiling from one to produce another.
- **`build/` and `dist/`** are gitignored — treat them as disposable output,
  regenerate with the command above whenever you want a fresh binary.
- **Saves live next to the executable**: `gold.json`/`meta_upgrades.json`/
  `run_history.json` are created beside whatever `.exe` (or binary) you're
  running, not in some fixed install location — so the whole thing (progress
  included) travels as one file. Sharing a fresh copy with someone gives them
  a fresh save; copying *their* `.exe` back preserves it.

---

## Deploying the Web Build

The game also runs in a browser via [pygbag](https://pypi.org/project/pygbag/)
(compiles CPython + pygame-ce to WebAssembly), embedded on
[orionpal.com](https://orionpal.com) at `/projects/embeds/mazey-boy`.

```bash
python3 deploy_web.py
```

This stages a clean copy of just the shipped source (`main.py`, `maze_game/`,
`assets/`), builds it with pygbag, and copies the result into the
orionpal.com repo's `public/mazey-boy/` — by default assumed to be cloned as
a sibling directory next to this one (`--site-dir` overrides that). It
installs `pygbag` into `.venv` automatically the first time. It does **not**
commit or push anything — review the diff it prints and commit/push both
repos yourself.

Run this any time game logic changes and you want the live site updated.

---

## Labyrinth Progression Mode (`main.py`)

A run of 100 mazes, starting small (9x9) and gradually growing to 41x41,
each with its own time limit shown as a countdown. Every 5 mazes stitch
together seamlessly (finish one, the next starts immediately); after each
group of 5 there's a break screen until you resume. Running out of time on
any maze ends the run back at maze 1.

| Key | Action |
|-----|--------|
| `↑ ↓ ← →` | Slide the player |
| `Space` | Resume from a between-group break |
| `R` | Restart from maze 1 (after a fail or a full clear) |
| `Esc` | Pause (Resume / Return to Base); `Esc` again resumes |

This is a first playtestable pass, not a balance pass — see
`docs/progression.md` for exactly how the dimensions ramp, time limits, and
fail behavior were chosen, and which of those are expected to need retuning.

---

## Free-Play Mode (`mvp_main.py`)

A single maze at a time, no time limit — useful for practicing or just
adjusting settings without the pressure of a timed run. The window has
three parts: a **left sidebar** for adjusting maze size, the **maze** in
the middle, and a **right sidebar** logging your past runs (dimensions,
time, date — persisted to `run_history.json` between sessions).

| Key | Action |
|-----|--------|
| `↑ ↓ ← →` | Slide the player in that direction |
| `R` | Generate a new maze and restart the timer |
| `Esc` / `Q` | Quit |

Click the `-`/`+` buttons in the left sidebar to change the number of columns/rows — this immediately starts a fresh maze at the new size (clamped to 9–41, always odd, since the carver requires it).

---

## Assets (Sound & Icons)

Every entity currently renders as a plain shape and the game is silent — but
both are hook-ready: drop a `.wav`/`.ogg` into `assets/sounds/` or a `.png`
into `assets/icons/` (exact filenames in `assets/README.md`) and it's picked
up automatically, no code change needed. See `docs/assets.md` for the full
design and the complete event/icon-name vocabulary.

---

## Project Structure

```
maze-game/
├── main.py                  # Labyrinth-mode entry point (100-maze run)
├── mvp_main.py             # Free-play entry point — pygame loop & input handling
├── requirements.txt         # Python dependencies
├── README.md
├── docs/                    # Design notes & audits (kept up to date as we build)
├── tests/                   # pytest suite for maze/player/game logic (no display needed)
└── maze_game/               # Game package
    ├── __init__.py          # Public package surface
    ├── constants.py         # Grid size, colours, display settings, labyrinth-mode tuning
    ├── maze.py              # Maze generation, BFS utilities, shortest-path
    ├── player.py            # Sliding movement logic
    ├── game.py              # Free-play game state (grid, player, timer, dimensions, history)
    ├── history.py           # Free-play run-history persistence (JSON on disk)
    ├── progression.py       # Labyrinth-mode state machine (LabyrinthRun)
    └── renderer.py          # Free-play pygame drawing + sidebar/window layout
```

Run the tests with `pip install pytest && pytest`.

### Module responsibilities

**`constants.py`** — The single source of truth for every tuneable value (grid dimensions, colours, FPS). Change things here to customise the game without touching logic.

**`maze.py`** — Procedural maze generation (Growing Tree algorithm — a tunable generalization that covers the recursive backtracker/DFS as one special case — plus an optional braid pass; see `docs/maze-generation.md`) and BFS helpers (farthest reachable cell for goal placement, shortest path for the labyrinth mode's time-limit estimate).

**`player.py`** — The sliding movement algorithm. The player moves cell-by-cell in the chosen direction, stopping at walls or junctions (cells with 3+ open neighbours).

**`progression.py`** — `LabyrinthRun`, the labyrinth-mode state machine: which maze you're on, its dimensions/time limit, group breaks, and pass/fail. Pure logic, no pygame dependency, same pattern as `game.py`/`history.py`. See `docs/progression.md`.

**`main.py`** — Labyrinth-mode pygame loop: maze + countdown HUD + break/fail/victory overlays.

**`game.py`** — Owns free-play's mutable round state: the grid, player position, goal position, elapsed time, best time, adjustable dimensions, and the run-history log. Delegates to `maze.py`, `player.py`, and `history.py`.

**`history.py`** — Loads/saves free-play's run-history log (`run_history.json`, gitignored — it's per-player save data) as a list of `RunRecord(cols, rows, seconds, finished_at)`. Pure logic, no pygame dependency.

**`renderer.py`** — Free-play's drawing code plus the `Layout` class, which computes every rect (maze offset, sidebar bounds, +/- button positions) from the current cols/rows. `mvp_main.py` reuses the same `Layout` for mouse click hit-testing, so drawing and click detection can never drift out of sync.

**`mvp_main.py`** — Initialises pygame, maps key events to free-play game actions, and runs the frame loop.

---

## Roadmap

- [x] Controls audit — see `docs/controls-audit.md` (fixed a recursion-limit bug in maze generation; movement/timer logic confirmed solid via `tests/`)
- [x] More branching maze generation — DFS replaced with tunable Growing Tree + braid pass, see `docs/maze-generation.md` (~doubled junction density; old DFS feel still reachable via `newest_prob=1.0`)
- [x] Sidebar UI — left panel for adjustable maze dimensions, right panel logging past runs (dimensions, time, date), persisted to `run_history.json`
- [x] Labyrinth progression mode — 100-maze run, growing size, per-maze time limits, group breaks; see `docs/progression.md` (first pass, needs playtesting). Promoted to `main.py`; the original single-maze mode is now `mvp_main.py`.
- [x] Fix single-wall-pillar loops in maze generation — braid() could isolate one wall pixel inside a 1-cell loop; see `docs/maze-generation.md`
- [x] Fix unsolvable mazes — goal could be placed on an unreachable pass-through cell (~18% of mazes), and labyrinth time limits under-counted forced stops at junctions; see `docs/maze-generation.md` and `docs/progression.md`
- [ ] Progress tracker polish (bigger/clearer "maze N/100" display, visual group indicator)
- [ ] Merge labyrinth and free-play modes into one entry point with a mode switch, now that labyrinth mode is the default experience
- [ ] Persistent history/leaderboard for labyrinth runs (mazes reached, total time)
- [ ] Tile-variety pool for maze cells, decoupled from topology — see `docs/maze-generation.md` for why this replaces a straight WFC swap
- [ ] Expose `newest_prob`/`braid_prob` (branchiness) as a live sidebar control alongside dimensions
- [ ] Difficulty selector (grid size, algorithm)
- [ ] Leaderboard view (best times ranked, distinct from the chronological history log)
- [ ] Animated player movement
- [ ] Sound effects
