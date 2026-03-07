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
└── maze_game/               # Game package
    ├── __init__.py          # Public package surface
    ├── constants.py         # Grid size, colours, display settings
    ├── maze.py              # Maze generation & BFS utilities
    ├── player.py            # Sliding movement logic
    ├── game.py              # Game state (grid, player, timer, win condition)
    └── renderer.py          # All pygame drawing code
```

### Module responsibilities

**`constants.py`** — The single source of truth for every tuneable value (grid dimensions, colours, FPS). Change things here to customise the game without touching logic.

**`maze.py`** — Procedural maze generation (currently Recursive Backtracker / DFS) and a BFS helper that finds the farthest reachable cell from a given start point, which is used to place the goal.

**`player.py`** — The sliding movement algorithm. The player moves cell-by-cell in the chosen direction, stopping at walls or junctions (cells with 3+ open neighbours).

**`game.py`** — Owns all mutable round state: the grid, player position, goal position, elapsed time, and best time. Delegates to `maze.py` and `player.py`.

**`renderer.py`** — Pure drawing code. Takes state from `Game` and paints a frame. Contains no game logic.

**`main.py`** — Initialises pygame, maps key events to game actions, and runs the frame loop.

---

## Roadmap

- [ ] Wave Function Collapse maze generator (drop-in replacement for `generate_maze` in `maze.py`)
- [ ] Difficulty selector (grid size, algorithm)
- [ ] Leaderboard / persistent best times
- [ ] Animated player movement
- [ ] Sound effects
