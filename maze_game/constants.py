"""
constants.py
------------
All tuneable game settings live here. Change values in this file to
customise the look and feel without touching game logic.
"""

# ── Grid dimensions ────────────────────────────────────────────────────────
# Cols/rows are runtime-adjustable via the left sidebar (see Game.set_dimensions),
# these are just the starting values. Must stay odd (the maze carver requires
# it) — MIN/MAX/STEP keep the sidebar +/- buttons on odd values automatically.
DEFAULT_COLS = 21
DEFAULT_ROWS = 21
MIN_DIMENSION = 9
MAX_DIMENSION = 41
DIMENSION_STEP = 2  # always even, so odd + step stays odd

# ── Display ───────────────────────────────────────────────────────────────
CELL         = 28          # pixels per maze cell
SIDEBAR_W    = 230         # width of each side panel
HUD_HEIGHT   = 60          # bottom bar height
FPS          = 60

# History log
MAX_HISTORY_SHOWN = 12      # how many past runs the right sidebar lists

# ── Labyrinth progression mode ──────────────────────────────────────────────
# See docs/progression.md for how these were chosen -- all first-guess
# starting values, meant to be retuned after playtesting.
LABYRINTH_TOTAL_MAZES = 100
LABYRINTH_GROUP_SIZE  = 5     # mazes per group; a break+resume prompt follows each group
# Dimensions ramp: MIN_DIMENSION at group 1, +DIMENSION_STEP per group after
# that, capped at MAX_DIMENSION (reused from the free-play sidebar bounds
# above, rather than inventing a separate ceiling).
LABYRINTH_TIME_BASE      = 0.0    # seconds, flat per-maze buffer (orientation time)
LABYRINTH_TIME_PER_TURN  = 2.0    # seconds budgeted per direction-change needed on the shortest path

# ── Colours  (R, G, B) ────────────────────────────────────────────────────
C_BG        = (15,  15,  25)
C_WALL      = (40,  80, 140)
C_FLOOR     = (20,  20,  35)
C_PLAYER    = (80, 220, 120)
C_GOAL      = (220, 80,  80)
C_TEXT      = (220, 220, 220)
C_DIM       = (100, 100, 120)
C_FLASH     = (255, 220,  60)
C_HUD_BG    = (10,  10,  20)
C_PANEL_BG  = (18,  18,  30)
C_PANEL_LINE = (45,  45,  65)
C_BUTTON    = (35,  60, 100)
C_BUTTON_HOVER = (55, 90, 140)
