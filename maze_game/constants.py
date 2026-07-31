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
# (augment) choice every AUGMENT_INTERVAL mazes. When a maze index is a
# multiple of more than one of these, the breaks stack sequentially
# (power-up screen, then modifier screen) rather than one replacing another
# -- see progression/run.py::_breaks_due_after().
AUGMENT_INTERVAL = 10

# Milestone mazes: every MILESTONE_INTERVAL-th maze, and always the
# LABYRINTH_TOTAL_MAZES-th (final) maze, gets a one-off dimension "spike" --
# noticeably bigger than the normal ramp would give it, reverting to the
# regular ramp on the very next maze (see run.py::dimensions_for_maze()).
# Otherwise a totally ordinary maze: real goal, normal pellet/enemy/gold
# spawning. MILESTONE_INTERVAL must land on a group boundary (a power-up
# break already exists there) -- see the assertion next to its use in
# run.py. MILESTONE_DIMENSION_BOOST must stay even (so odd + boost stays
# odd, matching DIMENSION_STEP's own parity requirement); several
# milestones (90, 100) already sit at MAX_DIMENSION under the normal ramp,
# so the spike needs its own higher ceiling to have anywhere to jump to.
MILESTONE_INTERVAL       = 30
MILESTONE_DIMENSION_BOOST = 16
MILESTONE_MAX_DIMENSION   = 61

# Maze augments (progression/augments/): generation-time modifiers (e.g.
# teleporting squares) offered every AUGMENT_INTERVAL-th maze. Capped at
# MAX_ACTIVE_AUGMENTS distinct augments active per run; once capped, further
# picks level up an already-active augment instead (same multiplicative-
# stacking shape as perks -- see progression/shop/perks.py).
MAX_ACTIVE_AUGMENTS = 4

# Time is one persistent resource carried across the whole run (rogue-like),
# not a per-maze budget: it ticks down continuously, pellets add to it,
# enemies subtract from it, and it's only reset on death (restart()).
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

# Perk magnitudes (multiplicative -- stacking compounds, see progression/shop/perks.py).
PELLET_FREQUENCY_PERK_MAGNITUDE = 1.2
PELLET_VALUE_PERK_MAGNITUDE     = 1.3

# Items (progression/shop/items.py): Q/W/E/R active abilities, each gated by
# a charge count in Loadout (except Squeaky Toy, which is unlimited).
# Wall Breaker and Laser have no other numeric knobs -- their effect is a
# single wall-open / all-enemies-in-4-directions action, not a magnitude.
STOPWATCH_PAUSE_SECONDS = 5.0  # seconds paused per Stopwatch charge used

# Feedback popups: a brief floating "+Xs"/"-Xs" label wherever a pellet,
# enemy, or maze-clear speed bonus changes the time resource, so the effect
# is legible in the moment instead of only visible via the HUD ticking.
POPUP_DURATION_SECONDS = 1.0
POPUP_RISE_PIXELS      = 24   # total upward drift over the popup's lifetime

# Gold: a persistent meta-currency, separate from the time resource -- it
# survives death/restart (loaded once at LabyrinthRun.__init__, saved to
# disk on every pickup) rather than resetting each run like time does.
# Collect + display only for now; no spending mechanic yet. Deliberately
# rare (a maze has a GOLD_SPAWN_CHANCE chance of containing exactly one),
# unlike time pellets, which scale with maze size -- gold is meant to feel
# like a special find, not a routine top-up.
GOLD_PELLET_VALUE = 1
GOLD_SPAWN_CHANCE = 0.3

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

# Doors & Keys (progression/augments/doors.py): the second maze augment. A
# locked door blocks progress until its matching key -- placed somewhere
# reachable before the door -- is collected. Same level-scaling shape as
# teleporters above (mandatory doors gate the route to the goal;
# decorative doors gate an optional side pocket of bonus loot), tuned
# slightly more conservative since a mandatory door is a stronger
# constraint per pick than a decorative teleporter shortcut.
DOOR_PAIR_COUNT_BASE        = 2
DOOR_PAIR_COUNT_STEP        = 1
DOOR_PAIR_COUNT_MAX         = 5
DOOR_MANDATORY_COUNT_BASE   = 1
DOOR_MANDATORY_COUNT_STEP   = 1
DOOR_FAR_SIDE_MIN_SIZE      = 3   # cells gated behind one mandatory door
DOOR_FAR_SIDE_MAX_SIZE      = 10
DOOR_PLACEMENT_MAX_ATTEMPTS = 10  # retries per gated region before giving up on it (graceful degradation, never a crash/hang)

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
C_GOLD      = (255, 175,  20)  # warm amber-orange, distinct from C_PELLET's pale yellow
C_ENEMY     = (200, 60,   60)
C_SPEED_BONUS = (100, 220, 255)  # distinct from C_PELLET, so a maze-clear time bonus reads as its own thing
C_DOOR_LOCKED   = (140, 40,  40)
C_DOOR_UNLOCKED = (90, 180,  90)

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

# Door/key pairs: each pair drawn in its own colour (cycled by
# pair.color_index), same pattern as C_TELEPORT_PAIRS, so a key visually
# matches the door it unlocks. Doors themselves use C_DOOR_LOCKED/
# C_DOOR_UNLOCKED regardless of pair colour (lock state is the primary
# signal); this list is only for the still-uncollected key markers.
C_DOOR_KEY_PAIRS = [
    (230, 160, 60),
    (80,  200, 230),
    (210, 210, 90),
    (170, 100, 230),
    (120, 220, 160),
]
