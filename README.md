# Maze Game

A minimal, keyboard-driven maze game built with Python and pygame.

A new maze is procedurally generated each round. Press an arrow key and your dot slides in that direction until it hits a wall or reaches a junction — then you choose again. Reach the red goal as fast as you can.

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
python main.py
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

---

## Project Structure

```
maze-game/
├── main.py                  # Entry point — pygame loop & input handling
├── requirements.txt         # Python dependencies
├── README.md
├── docs/                    # Design notes & audits (kept up to date as we build)
├── tests/                   # pytest suite for maze/player/game logic (no display needed)
└── maze_game/               # Game package
    ├── __init__.py          # Public package surface
    ├── constants.py         # Grid size, colours, display settings
    ├── maze.py              # Maze generation & BFS utilities
    ├── player.py            # Sliding movement logic
    ├── game.py              # Game state (grid, player, timer, win condition)
    └── renderer.py          # All pygame drawing code
```

Run the tests with `pip install pytest && pytest`.

### Module responsibilities

**`constants.py`** — The single source of truth for every tuneable value (grid dimensions, colours, FPS). Change things here to customise the game without touching logic.

**`maze.py`** — Procedural maze generation (currently Recursive Backtracker / DFS) and a BFS helper that finds the farthest reachable cell from a given start point, which is used to place the goal.

**`player.py`** — The sliding movement algorithm. The player moves cell-by-cell in the chosen direction, stopping at walls or junctions (cells with 3+ open neighbours).

**`game.py`** — Owns all mutable round state: the grid, player position, goal position, elapsed time, and best time. Delegates to `maze.py` and `player.py`.

**`renderer.py`** — Pure drawing code. Takes state from `Game` and paints a frame. Contains no game logic.

**`main.py`** — Initialises pygame, maps key events to game actions, and runs the frame loop.

---

## Roadmap

- [x] Controls audit — see `docs/controls-audit.md` (fixed a recursion-limit bug in maze generation; movement/timer logic confirmed solid via `tests/`)
- [ ] Tile-variety pool for maze cells, decoupled from topology — see `docs/maze-generation.md` for why this replaces a straight WFC swap
- [ ] Alternate topology algorithms (Prim's / Kruskal's / Wilson's) for different maze "feels"
- [ ] Difficulty selector (grid size, algorithm)
- [ ] Leaderboard / persistent best times
- [ ] Animated player movement
- [ ] Sound effects
