"""
constants.py
------------
All tuneable game settings live here. Change values in this file to
customise the look and feel without touching game logic.
"""

import sys
from pathlib import Path

# ── Persistent save-file location ───────────────────────────────────────────
# gold.json/meta_upgrades.json/run_history.json all live next to APP_ROOT. In
# a normal checkout that's the repo root (__file__-relative). In a
# PyInstaller-frozen build (sys.frozen), __file__ instead resolves inside the
# temp extraction dir that's wiped after every run -- saves would silently
# reset on each launch -- so a frozen build routes this next to the .exe
# itself instead, which persists across runs and travels with it if moved.
if getattr(sys, "frozen", False):
    APP_ROOT = Path(sys.executable).resolve().parent
else:
    APP_ROOT = Path(__file__).resolve().parent.parent

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
# Otherwise a totally ordinary maze: real goal, normal pellet/hazard/gold
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
# hazards subtract from it, and it's only reset on death (restart()).
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

# Hazards: persistent hazards (not consumed on contact), unlocked partway
# through the run.
HAZARD_UNLOCK_MAZE  = 11       # hazards start appearing from this maze index onward
HAZARD_TIME_PENALTY = 3.0      # seconds lost on contact
HAZARD_DENSITY      = 0.5      # hazard count = density * sqrt(open cell count)
HAZARD_MAX_COUNT    = 6

# Ramp hazard density up gradually starting at HAZARD_UNLOCK_MAZE, rather than
# spawning at full density (~4-5 hazards) the instant the mechanic is
# introduced -- HAZARD_RAMP_START_MULTIPLIER is the density fraction on the
# unlock maze itself (~1 hazard), reaching full HAZARD_DENSITY (1.0x)
# HAZARD_RAMP_MAZES mazes later. See hazards.py::hazard_density_ramp().
HAZARD_RAMP_MAZES            = 10
HAZARD_RAMP_START_MULTIPLIER = 0.25

# More severe hazard variants (hazards.py::HeavyHazard/ExtremeHazard), each
# unlocked at its own later maze index -- same "introduced partway through,
# not from maze 1" shape as the base Hazard's own HAZARD_UNLOCK_MAZE, so a
# player has time to learn the base hazard before a costlier one shows up.
# hazards.py::hazard_types_for_maze() gates on the unlock maze and
# weighted-samples among whatever's unlocked so far using the WEIGHT
# constants below (relative to HAZARD_BASE_WEIGHT, not percentages) --
# both severer types stay a minority of spawns even once unlocked.
HAZARD_BASE_WEIGHT = 1.0

HAZARD_HEAVY_UNLOCK_MAZE  = 31   # first appears partway through group 7 (mazes 31-35)
HAZARD_HEAVY_TIME_PENALTY = 8.0  # seconds lost on contact -- well above the base hazard's 3.0s
HAZARD_HEAVY_WEIGHT       = 0.4

# The harshest hazard in the game: rather than a flat penalty, takes a
# fraction of whatever time the player currently has banked -- scales with
# (and punishes) hoarded time rather than being a fixed cost a late-game
# player with a large buffer can shrug off. Rarer and later than HeavyHazard.
HAZARD_EXTREME_UNLOCK_MAZE   = 61
HAZARD_EXTREME_TIME_FRACTION = 0.5   # halves the player's current banked time
HAZARD_EXTREME_WEIGHT        = 0.15

# Perk magnitudes (additive -- each pick adds one more charge/bonus unit,
# see progression/shop/perks.py).
HAZARD_SHIELD_CHARGES_PER_LEVEL = 1  # Bulwark: ignored hazard contacts per maze, per pick
GOLD_RUSH_BONUS_PER_LEVEL      = 1  # Speedrunner: bonus gold on an under-par clear, per pick

# Feedback popups: a brief floating "+Xs"/"-Xs" label wherever a pellet,
# hazard, or maze-clear speed bonus changes the time resource, so the effect
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

# Meta-progression (progression/meta/): permanent upgrades bought with gold
# in the Base, between runs -- distinct from the per-run Perk shop, which
# resets to nothing on death. Each upgrade is repurchasable at an
# increasing gold cost (cost_base + cost_step * current_level), and its
# effect stacks multiplicatively the same way in-run perks do (reusing
# shop/perks.py's EFFECTS dict -- see MetaProgress.seed_build()). Magnitudes
# are deliberately gentler than the equivalent in-run perk's, since a meta
# upgrade's level accumulates indefinitely across every future run rather
# than being capped by how many break screens one run has.
META_PELLET_VALUE_MAGNITUDE     = 1.1   # +10% pellet time per level
META_HAZARD_RESISTANCE_MAGNITUDE = 0.9   # -10% hazard damage per level
META_UPGRADE_COST_BASE = 5
META_UPGRADE_COST_STEP = 4

# Teleporting squares (progression/augments/teleporters.py): the first maze
# augment. Pair count and how many of those pairs are load-bearing (the
# goal is unreachable without using them) both scale with the augment's
# level (its pick count in AugmentBuild -- see progression/augments/), same
# density-formula shape as pellets/hazards above.
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

# Multi-Level Mazes (progression/augments/multi_level.py): the third maze
# augment. Unlike teleporters (reuse the sealed pocket's original interior)
# or doors (gate the original interior behind a key), each pocket's own
# internal layout is discarded and recarved from scratch as an independent
# "floor" -- a genuinely different maze occupying the same footprint,
# reachable only via a linked stairs pair (mechanically identical to a
# teleporter pair). Same level-scaling shape as teleporters/doors above:
# floor count and how many of those floors are load-bearing both scale with
# the augment's level, higher levels nesting mandatory floors deeper.
MULTI_LEVEL_FLOOR_COUNT_BASE       = 2
MULTI_LEVEL_FLOOR_COUNT_STEP       = 1
MULTI_LEVEL_FLOOR_COUNT_MAX        = 5
MULTI_LEVEL_MANDATORY_COUNT_BASE   = 1
MULTI_LEVEL_MANDATORY_COUNT_STEP   = 1
MULTI_LEVEL_FLOOR_MIN_SIZE         = 4   # cells recarved into one floor's own footprint
MULTI_LEVEL_FLOOR_MAX_SIZE         = 12
MULTI_LEVEL_PLACEMENT_MAX_ATTEMPTS = 10  # retries per floor before giving up on it (graceful degradation, never a crash/hang)

# ── Colours  (R, G, B) ────────────────────────────────────────────────────
# Identity colours (player/goal/pellet/gold/hazard/door/speed-bonus) are
# deliberately spread across distinct hues so entity *families* stay
# distinguishable at a glance: red = danger (hazard, locked door), green =
# player-exclusive, yellow/orange = resources (pellet, gold), magenta =
# the goal (previously red, colliding with hazard/locked-door), teal =
# unlocked/safe (previously green, colliding with the player). First-pass
# values, tunable like everything else here -- not a final art pass.
C_BG        = (15,  15,  25)
C_WALL      = (40,  80, 140)
C_FLOOR     = (20,  20,  35)
C_PLAYER    = (80, 220, 120)
C_GOAL      = (230, 90, 200)   # magenta -- was (220,80,80), colliding with C_HAZARD/C_DOOR_LOCKED
C_TEXT      = (220, 220, 220)
C_DIM       = (100, 100, 120)
C_CARD_DESC = (190, 195, 210)  # card/tooltip description text -- brighter than C_DIM, dimmer than C_TEXT, legible against C_BUTTON's blue
C_FLASH     = (255, 220,  60)
C_HUD_BG    = (10,  10,  20)
C_PANEL_BG  = (18,  18,  30)
C_PANEL_LINE = (45,  45,  65)
C_BUTTON    = (35,  60, 100)
C_BUTTON_HOVER = (55, 90, 140)
C_PELLET    = (240, 220,  80)
C_GOLD      = (255, 150,  30)  # pushed further from C_PELLET's pale yellow than before
C_HAZARD     = (220, 60,   60)
C_HAZARD_HEAVY   = (255, 110,  10)  # deeper orange-red -- reads as "worse than the base hazard" while staying in the same danger hue
C_HAZARD_EXTREME = (140,  20, 120)  # magenta-purple -- deliberately the odd one out among hazard colours, so it never reads as "just a bigger red square"
C_SPEED_BONUS = (100, 220, 255)  # distinct from C_PELLET, so a maze-clear time bonus reads as its own thing
C_DOOR_LOCKED   = (170, 70,  40)   # brick -- was (140,40,40), colliding with C_HAZARD/C_GOAL
C_DOOR_UNLOCKED = (60, 190, 170)   # teal -- was (90,180,90), colliding with C_PLAYER
C_SHIELD        = (190, 210, 230)  # pale blue/silver -- Bulwark's "Shielded!" popup, distinct from C_HAZARD's red

# Teleporter pairs: each pair drawn in its own colour (cycled by
# pair.color_index if there are more pairs than colours), so linked cells
# are visually identifiable as belonging to each other. Blue/purple/teal-
# leaning, so this palette doesn't alias C_DOOR_KEY_PAIRS below.
C_TELEPORT_PAIRS = [
    (80,  160, 230),
    (170, 90,  230),
    (90,  220, 190),
    (230, 130, 230),
    (120, 140, 230),
    (60,  200, 220),
]

# Door/key pairs: each pair drawn in its own colour (cycled by
# pair.color_index), same pattern as C_TELEPORT_PAIRS, so a key visually
# matches the door it unlocks. Doors themselves use C_DOOR_LOCKED/
# C_DOOR_UNLOCKED regardless of pair colour (lock state is the primary
# signal); this list is only for the still-uncollected key markers.
# Rose/peach/lavender-leaning, so it doesn't alias C_TELEPORT_PAIRS above.
C_DOOR_KEY_PAIRS = [
    (230, 170, 190),
    (140, 200, 230),
    (200, 150, 255),
    (255, 190, 140),
    (170, 220, 140),
]

# Stairs pairs (multi-level mazes): each pair drawn in its own colour
# (cycled by pair.color_index), same pattern as C_TELEPORT_PAIRS/
# C_DOOR_KEY_PAIRS. Stone/earth-leaning, so this palette doesn't alias
# either of those.
C_STAIRS_PAIRS = [
    (170, 150, 90),
    (110, 150, 100),
    (150, 170, 190),
    (190, 150, 120),
    (130, 180, 160),
]
