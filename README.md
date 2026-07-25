# Maze Game

A minimal, keyboard-driven maze game built with Python and pygame.

A new maze is procedurally generated each round. Press an arrow key and your dot slides in that direction until it hits a wall or reaches a junction — then you choose again. Reach the red goal as fast as you can.

The window has three parts: a **left sidebar** for adjusting maze size, the **maze** in the middle, and a **right sidebar** logging your past runs (dimensions, time, date — persisted to `run_history.json` between sessions).

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
python main.py              # free play: adjustable size, no time limit
python progression_main.py  # labyrinth mode: 100 mazes, gradually bigger, timed -- see docs/progression.md
```

---

## Building a Standalone Executable

No need to have Python/pip installed to just play it — [PyInstaller](https://pyinstaller.org/) bundles the interpreter, pygame, and the game into one file:

```bash
pip install pyinstaller
pyinstaller --onefile --name maze-game main.py
```

The executable lands in `dist/maze-game` (`dist/maze-game.exe` on Windows) — a
single ~16MB file with no dependencies to install; just double-click it (or
run it) to play. A couple of things worth knowing:

- **Not cross-platform to build**: PyInstaller packages for whatever OS you
  run it *on* — build on Windows for a `.exe`, macOS for a Mac app, Linux for
  an ELF binary. There's no cross-compiling from one to produce another.
- **`build/` and `dist/`** are gitignored — treat them as disposable output,
  regenerate with the command above whenever you want a fresh binary.

---

## Controls

| Key | Action |
|-----|--------|
| `↑ ↓ ← →` | Slide the player in that direction |
| `R` | Generate a new maze and restart the timer |
| `Esc` / `Q` | Quit |

Click the `-`/`+` buttons in the left sidebar to change the number of columns/rows — this immediately starts a fresh maze at the new size (clamped to 9–41, always odd, since the carver requires it).

---

## Labyrinth Progression Mode

`python progression_main.py` — a run of 100 mazes, starting small (9x9) and
gradually growing to 41x41, each with its own time limit shown as a
countdown. Every 5 mazes stitch together seamlessly (finish one, the next
starts immediately); after each group of 5 there's a break screen until you
resume. Running out of time on any maze ends the run back at maze 1.

| Key | Action |
|-----|--------|
| `↑ ↓ ← →` | Slide the player |
| `Space` | Resume from a between-group break |
| `R` | Restart from maze 1 (after a fail or a full clear) |
| `Esc` | Quit |

This is a first playtestable pass, not a balance pass — see
`docs/progression.md` for exactly how the dimensions ramp, time limits, and
fail behavior were chosen, and which of those are expected to need retuning.

---

## Project Structure

```
maze-game/
├── main.py                  # Free-play entry point — pygame loop & input handling
├── progression_main.py      # Labyrinth-mode entry point (100-maze run)
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

**`maze.py`** — Procedural maze generation (Growing Tree algorithm — a tunable generalization that covers the recursive backtracker/DFS as one special case — plus an optional braid pass; see `docs/maze-generation.md`) and a BFS helper that finds the farthest reachable cell from a given start point, which is used to place the goal.

**`player.py`** — The sliding movement algorithm. The player moves cell-by-cell in the chosen direction, stopping at walls or junctions (cells with 3+ open neighbours).

**`game.py`** — Owns all mutable round state: the grid, player position, goal position, elapsed time, best time, adjustable dimensions, and the run-history log. Delegates to `maze.py`, `player.py`, and `history.py`.

**`history.py`** — Loads/saves the run-history log (`run_history.json`, gitignored — it's per-player save data) as a list of `RunRecord(cols, rows, seconds, finished_at)`. Pure logic, no pygame dependency.

**`renderer.py`** — Drawing code plus the `Layout` class, which computes every rect (maze offset, sidebar bounds, +/- button positions) from the current cols/rows. `main.py` reuses the same `Layout` for mouse click hit-testing, so drawing and click detection can never drift out of sync.

**`main.py`** — Initialises pygame, maps key events to game actions, and runs the free-play frame loop.

**`progression.py`** — `LabyrinthRun`, the labyrinth-mode state machine: which maze you're on, its dimensions/time limit, group breaks, and pass/fail. Pure logic, no pygame dependency, same pattern as `game.py`/`history.py`. See `docs/progression.md`.

**`progression_main.py`** — Minimal pygame loop for labyrinth mode: maze + countdown HUD + break/fail/victory overlays. Deliberately separate from `main.py` rather than merged into the sidebar UI -- see the "not built yet" note in `docs/progression.md`.

---

## Roadmap

- [x] Controls audit — see `docs/controls-audit.md` (fixed a recursion-limit bug in maze generation; movement/timer logic confirmed solid via `tests/`)
- [x] More branching maze generation — DFS replaced with tunable Growing Tree + braid pass, see `docs/maze-generation.md` (~doubled junction density; old DFS feel still reachable via `newest_prob=1.0`)
- [x] Sidebar UI — left panel for adjustable maze dimensions, right panel logging past runs (dimensions, time, date), persisted to `run_history.json`
- [x] Labyrinth progression mode — 100-maze run, growing size, per-maze time limits, group breaks; see `docs/progression.md` (first pass, needs playtesting)
- [x] Fix single-wall-pillar loops in maze generation — braid() could isolate one wall pixel inside a 1-cell loop; see `docs/maze-generation.md`
- [ ] Merge progression mode into the main sidebar UI once its pacing is validated
- [ ] Persistent history/leaderboard for labyrinth runs (mazes reached, total time)
- [ ] Tile-variety pool for maze cells, decoupled from topology — see `docs/maze-generation.md` for why this replaces a straight WFC swap
- [ ] Expose `newest_prob`/`braid_prob` (branchiness) as a live sidebar control alongside dimensions
- [ ] Difficulty selector (grid size, algorithm)
- [ ] Leaderboard view (best times ranked, distinct from the chronological history log)
- [ ] Animated player movement
- [ ] Sound effects
