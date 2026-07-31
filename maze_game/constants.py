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
LABYRINTH_GROUP_SIZE  = 5     # mazes per group; a power-up (perk/item) break follows each group
# Dimensions ramp: MIN_DIMENSION at group 1, +DIMENSION_STEP per group after
# that, capped at MAX_DIMENSION (reused from the free-play sidebar bounds
# above, rather than inventing a separate ceiling).

# Pacing cadence: a power-up every LABYRINTH_GROUP_SIZE mazes, a maze-modifier
# (augment) choice every AUGMENT_INTERVAL mazes, a boss every BOSS_INTERVAL
# mazes, and the LABYRINTH_TOTAL_MAZES-th (final) maze is always a boss too,
# even though it isn't necessarily a BOSS_INTERVAL multiple -- see
# is_boss_maze()/boss_encounter_index() in progression/entities/boss.py.
# When a maze index is a multiple of more than one of these, the breaks
# stack sequentially (power-up screen, then modifier screen) rather than one
# replacing another -- see progression/run.py::_breaks_due_after().
AUGMENT_INTERVAL = 10

# Maze augments (progression/augments/): generation-time modifiers (e.g.
# teleporting squares) offered every AUGMENT_INTERVAL-th maze. Capped at
# MAX_ACTIVE_AUGMENTS distinct augments active per run; once capped, further
# picks level up an already-active augment instead (same multiplicative-
# stacking shape as perks -- see progression/shop/perks.py).
MAX_ACTIVE_AUGMENTS = 4

# Time is one persistent resource carried across the whole run (rogue-like),
# not a per-maze budget: it ticks down continuously, pellets add to it,
# enemies/the boss subtract from it, and it's only reset on death (restart()).
LABYRINTH_START_TIME = 15.0   # seconds the run starts with

# Speed bonus: clearing a maze quickly adds a little time back. "Fast
# enough" is judged against a par time derived from that specific maze's
# BFS shortest-path length (not a flat threshold, since mazes grow through
# the run) -- SPEED_BONUS_SECONDS_PER_CELL is set faster than the ~0.75s/
# cell a careful player needs on average (see docs/progression.md's old
# per-size measurements), so it rewards genuinely brisk play, not just
# "eventually got there."
SPEED_BONUS_TIME = 3.0
SPEED_BONUS_SECONDS_PER_CELL = 0.5

# Pellets: collectible, one-time time top-ups. Count scales with sqrt(open
# cell count) rather than a flat fraction, since traversal difficulty grows
# closer to linearly with maze size while a flat fraction of cells grows
# quadratically.
PELLET_TIME_VALUE = 1.0       # seconds gained per pellet (before perk multiplier)
PELLET_DENSITY    = 0.6       # pellet count = density * sqrt(open cell count)
PELLET_MIN_COUNT  = 2

# Enemies: persistent hazards (not consumed on contact), unlocked partway
# through the run.
ENEMY_UNLOCK_MAZE  = 11       # enemies start appearing from this maze index onward
ENEMY_TIME_PENALTY = 3.0      # seconds lost on contact
ENEMY_DENSITY      = 0.5      # enemy count = density * sqrt(open cell count)
ENEMY_MAX_COUNT    = 6

# Ramp enemy density up gradually starting at ENEMY_UNLOCK_MAZE, rather than
# spawning at full density (~4-5 enemies) the instant the mechanic is
# introduced -- ENEMY_RAMP_START_MULTIPLIER is the density fraction on the
# unlock maze itself (~1 enemy), reaching full ENEMY_DENSITY (1.0x)
# ENEMY_RAMP_MAZES mazes later. See hazards.py::enemy_density_ramp().
ENEMY_RAMP_MAZES            = 10
ENEMY_RAMP_START_MULTIPLIER = 0.25

# Boss: every BOSS_INTERVAL-th maze replaces the goal with a boss fight, and
# the LABYRINTH_TOTAL_MAZES-th (final) maze always is one too, whether or not
# it happens to be a BOSS_INTERVAL multiple. BOSS_INTERVAL must land on a
# group boundary (a power-up break already exists there) -- see the
# assertion next to its use in progression/entities/boss.py.
BOSS_INTERVAL    = 30
BOSS_BASE_HP     = 5
BOSS_HP_STEP     = 3          # extra HP per boss encounter (encounter 0, 1, 2, ...)
BOSS_BASE_DAMAGE = 1          # damage per idle-phase hit, before the strength perk multiplier

# Perk magnitudes (multiplicative -- stacking compounds, see progression/shop/perks.py).
PELLET_FREQUENCY_PERK_MAGNITUDE = 1.2
PELLET_VALUE_PERK_MAGNITUDE     = 1.3
STRENGTH_PERK_MAGNITUDE         = 1.5

# Items (progression/shop/items.py): Q/W/E/R active abilities, each gated by
# a charge count in Loadout (except Squeaky Toy, which is unlimited).
# Wall Breaker and Laser have no other numeric knobs -- their effect is a
# single wall-open / all-enemies-in-4-directions action, not a magnitude.
STOPWATCH_PAUSE_SECONDS = 5.0  # seconds paused per Stopwatch charge used

# Teleporting squares (progression/augments/teleporters.py): the first maze
# augment. Pair count and how many of those pairs are load-bearing (the
# goal is unreachable without using them) both scale with the augment's
# level (its pick count in AugmentBuild -- see progression/augments/), same
# density-formula shape as pellets/enemies above.
TELEPORT_PAIR_COUNT_BASE        = 3   # "a handful" of pairs at level 1
TELEPORT_PAIR_COUNT_STEP        = 1   # extra pairs per level above 1
TELEPORT_PAIR_COUNT_MAX         = 6
TELEPORT_MANDATORY_COUNT_BASE   = 1   # every pick guarantees >=1 real gate, never a no-op pick
TELEPORT_MANDATORY_COUNT_STEP   = 1   # extra mandatory pairs per level, capped at pair count
TELEPORT_POCKET_MIN_SIZE        = 3   # cells sealed off behind one mandatory pair
TELEPORT_POCKET_MAX_SIZE        = 8
TELEPORT_PLACEMENT_MAX_ATTEMPTS = 10  # retries per gated pocket before giving up on it (graceful degradation, never a crash/hang)

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
C_PELLET    = (230, 210,  70)
C_ENEMY     = (200, 60,   60)
C_BOSS_IDLE = (230, 90,  200)
C_BOSS_ACTIVE = (120, 40, 110)

# Teleporter pairs: each pair drawn in its own colour (cycled by
# pair.color_index if there are more pairs than colours), so linked cells
# are visually identifiable as belonging to each other.
C_TELEPORT_PAIRS = [
    (80,  200, 230),
    (230, 160, 60),
    (170, 100, 230),
    (120, 220, 160),
    (230, 90,  140),
    (210, 210, 90),
]
