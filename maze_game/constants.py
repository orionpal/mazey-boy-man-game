"""
constants.py
------------
All tuneable game settings live here. Change values in this file to
customise the look and feel without touching game logic.
"""

import sys
from pathlib import Path

# ── Platform detection ──────────────────────────────────────────────────────
# pygbag runs the game under Emscripten/Pyodide, where sys.platform reports
# "emscripten". Used to route around desktop-only APIs (pygame._sdl2.video.Window
# in particular -- see main.py/mvp_main.py/progression/app.py/freeplay/app.py)
# that have no browser equivalent.
IS_WEB = sys.platform == "emscripten"

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

# Pellet value ramp: mazes grow bigger and (from HAZARD_UNLOCK_MAZE) hazards
# ramp in, but a flat PELLET_TIME_VALUE wasn't keeping pace -- later mazes
# felt starved for time even with careful play. Starting at
# PELLET_VALUE_RAMP_START_MAZE, pellet value ramps from 1.0x up to
# PELLET_VALUE_RAMP_END_MULTIPLIER over the following PELLET_VALUE_RAMP_MAZES
# mazes, same ramp shape as hazard_density_ramp() below.
PELLET_VALUE_RAMP_START_MAZE     = 20
PELLET_VALUE_RAMP_MAZES          = 10
PELLET_VALUE_RAMP_END_MULTIPLIER = 1.5

# Pellet kinds: most spawns are plain (PELLET_TIME_VALUE, no side effect);
# a minority are one of five colored variants with their own on-contact
# effect (see progression/entities/hazards.py::PELLET_KIND_EFFECTS).
# PELLET_KIND_WEIGHTS is a random.choices() weight table, not a
# probability (doesn't need to sum to 1) -- plain dominates heavily so a
# colored pellet reads as a small, noticeable event, not the norm.
PELLET_KIND_PLAIN    = "plain"
PELLET_KIND_DOUBLE   = "double"     # 2x time value, nothing else
PELLET_KIND_VOLATILE = "volatile"   # bigger time value, but spawns one extra hazard elsewhere
PELLET_KIND_CHAIN    = "chain"      # no time itself -- multiplies the *next* pellet's value
PELLET_KIND_FREEZE   = "freeze"     # no time -- pauses hazards/rotation, briefly
PELLET_KIND_GAMBLE   = "gamble"     # 50/50: big time bonus, or your banked time is halved

PELLET_KIND_WEIGHTS: dict[str, int] = {
    PELLET_KIND_PLAIN:    80,
    PELLET_KIND_DOUBLE:   6,
    PELLET_KIND_VOLATILE: 5,
    PELLET_KIND_CHAIN:    5,
    PELLET_KIND_FREEZE:   5,
    PELLET_KIND_GAMBLE:   4,
}

# Multiplier baked into Pellet.value at spawn time (on top of
# PELLET_TIME_VALUE * the ramp/frequency multipliers spawn_pellets()
# already applies). Chain/Freeze grant no time directly, hence 0.0 --
# their effect is entirely in PELLET_KIND_EFFECTS. Gamble's swing (4x win /
# half your banked time on a loss) happens at contact time, not spawn
# time, so its spawn-time multiplier is a neutral 1.0.
PELLET_KIND_VALUE_MULTIPLIERS: dict[str, float] = {
    PELLET_KIND_PLAIN:    1.0,
    PELLET_KIND_DOUBLE:   2.0,
    PELLET_KIND_VOLATILE: 2.5,
    PELLET_KIND_CHAIN:    0.0,
    PELLET_KIND_FREEZE:   0.0,
    PELLET_KIND_GAMBLE:   1.0,
}

PELLET_VOLATILE_EXTRA_HAZARD_COUNT = 1
PELLET_FREEZE_DURATION_SECONDS     = 4.0
PELLET_CHAIN_MULTIPLIER            = 2.0   # multiplies the next pellet's value; stacks if picked up again first
PELLET_GAMBLE_WIN_CHANCE           = 0.5
PELLET_GAMBLE_WIN_MULTIPLIER       = 4.0
PELLET_GAMBLE_LOSE_FRACTION        = 0.5   # fraction of the player's *current banked time* lost on a bad roll

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

# Perk magnitudes (additive -- each pick adds one more charge/bonus unit,
# see progression/shop/perks.py).
HAZARD_SHIELD_CHARGES_PER_LEVEL = 1  # Bulwark: ignored hazard contacts per maze, per pick
GOLD_RUSH_BONUS_PER_LEVEL      = 1  # Speedrunner: bonus gold on an under-par clear, per pick
MOMENTUM_PELLET_VALUE_BONUS_PER_LEVEL = 0.1   # Momentum: permanent pellet-value bump per hazard-free maze clear, per pick
COMPOUND_INTEREST_RATE_PER_LEVEL      = 0.01  # Compound Interest: seconds of time per held gold per second, per pick
# Hard ceiling on gold * compound_interest_rate (the effective seconds-
# gained-per-second-elapsed multiplier), regardless of how much gold is
# held or how many levels are stacked -- enough gold/levels previously let
# this exceed 1.0, meaning the passive trickle outpaced the time
# resource's own drain and the run's timer would literally count up
# instead of down. 0.1 means "at most 1 second back for every 10 seconds
# elapsed," comfortably below the 1.0x drain rate no matter what.
COMPOUND_INTEREST_MAX_RATE            = 0.1
SECOND_WIND_CHARGES_PER_LEVEL         = 1     # Second Wind: extra "don't actually fail" charges this run, per pick
SECOND_WIND_REFILL_SECONDS            = 5.0   # time refilled to when a Second Wind charge is spent
PEEK_FADE_SECONDS_PER_LEVEL           = 4.0   # Peek: pause overlay fade-in duration, per pick (0 = instantly opaque, the no-perk default)

# Feedback popups: a brief floating "+Xs"/"-Xs" label wherever a pellet,
# hazard, or maze-clear speed bonus changes the time resource, so the effect
# is legible in the moment instead of only visible via the HUD ticking.
POPUP_DURATION_SECONDS = 1.0
POPUP_RISE_PIXELS      = 24   # total upward drift over the popup's lifetime

# A teleport hop is the one genuinely discontinuous player move (an
# ordinary slide already reads as continuous, one grid-cell-to-the-next
# movement) -- renderer._draw_player() linearly interpolates the on-screen
# position over this short window instead of an instant snap, purely
# presentational (LabyrinthRun.player's actual grid position updates
# instantly in move(), unaffected). Deliberately quick: a "zip", not a
# real animation.
ZIP_ANIMATION_DURATION_SECONDS = 0.12

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
# Pellet-economy trade-off (see augments/__init__.py's Augment docstring):
# a mandatory teleporter gate plus decorative shortcuts is a moderate
# difficulty increase (find the hidden linked pair), so pellets compensate
# a little.
TELEPORT_PELLET_FREQUENCY_MULTIPLIER = 1.15
TELEPORT_PELLET_VALUE_MULTIPLIER     = 1.1

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
# Pellet-economy trade-off: a mandatory door is a fetch-quest detour (find
# the key, backtrack to the door) -- extra distance/time pressure beyond
# what a teleporter gate costs, so a slightly stronger compensation.
DOOR_PELLET_FREQUENCY_MULTIPLIER = 1.2
DOOR_PELLET_VALUE_MULTIPLIER     = 1.15

# Shifting Room (progression/augments/shifting_room.py): the third gating
# augment. A pocket is sealed *completely* (a real wall, not a behavioral
# gate like doors) except for one boundary crossing, which stays closed
# until the player steps on its pressure pad -- unlike teleporters/doors,
# which only ever mutate the grid once at generation time, a pad's effect
# happens at runtime. One-shot (opens permanently, no toggle-back) and
# fires the instant the player slides *over* the pad, not only if they
# stop there -- see player.slide_path()'s pressure_pad hook. Same
# level-scaling shape as teleporters/doors.
SHIFT_PAD_COUNT_BASE        = 2
SHIFT_PAD_COUNT_STEP        = 1
SHIFT_PAD_COUNT_MAX         = 5
SHIFT_MANDATORY_COUNT_BASE  = 1
SHIFT_MANDATORY_COUNT_STEP  = 1
SHIFT_POCKET_MIN_SIZE       = 3   # cells sealed off behind one mandatory pad
SHIFT_POCKET_MAX_SIZE       = 10
SHIFT_PLACEMENT_MAX_ATTEMPTS = 10  # retries per gated pocket before giving up on it (graceful degradation, never a crash/hang)
# Pellet-economy trade-off: a pocket sealed behind a hidden pressure pad is
# comparable in difficulty to a mandatory door/teleporter gate (find the
# trigger, no visible indication where it is until stepped on).
SHIFT_PELLET_FREQUENCY_MULTIPLIER = 1.15
SHIFT_PELLET_VALUE_MULTIPLIER     = 1.1

# Rotating maze (progression/augments/runtime/rotation.py): the whole grid
# rotates 90 degrees clockwise on a fixed timer, with a warning arrow
# shortly before each rotation fires. Purely a runtime effect (no
# generation-time apply()) -- a rigid rotation of the grid + every entity
# position together is an isometry, so unlike every gating/ augment it
# needs no forced-use/solvability verification at all. Higher levels
# rotate faster (down to a floor, so it never becomes literally
# unplayable); the warning lead time deliberately stays flat across levels
# rather than also shrinking, to avoid compounding two
# disorientation-increasing changes into one.
ROTATE_INTERVAL_BASE_SECONDS = 2.0
ROTATE_INTERVAL_STEP_SECONDS = -0.3   # faster per level above 1
ROTATE_INTERVAL_MIN_SECONDS  = 1.0
ROTATE_WARNING_LEAD_SECONDS  = 0.75   # the warning arrow shows for this long before each rotation
# Pellet-economy trade-off: periodic forced re-planning (everything you'd
# memorized gets rotated out from under you) is an ongoing difficulty tax,
# not a one-time gate -- compensated a bit more than the gating augments
# above.
ROTATE_PELLET_FREQUENCY_MULTIPLIER = 1.25
ROTATE_PELLET_VALUE_MULTIPLIER     = 1.2

# Twin Goals (progression/augments/twin_goals.py): a second, independently
# reachable goal cell -- reaching either one clears the maze. Candidates
# must be at least these *fractions* of the farthest reachable distance
# from the player's start and from the primary goal respectively (not an
# absolute cell count -- mazes range from 9x9 to 61x61 over a run), so the
# secondary goal is never right next to spawn or clustered on top of the
# primary goal. See maze.py::secondary_goal_candidate().
TWIN_GOAL_MIN_START_DISTANCE_FRACTION = 0.5
TWIN_GOAL_MIN_GOAL_DISTANCE_FRACTION  = 0.3
# The bonus pellet cluster guaranteed near whichever of the two goals gets
# picked (see progression/entities/hazards.py::spawn_pellet_cluster_near()).
TWIN_GOAL_CLUSTER_SIZE   = 3
TWIN_GOAL_CLUSTER_RADIUS = 3
# Pellet-economy trade-off: two independent chances to end the maze is a
# genuine advantage (net easier, not harder, despite adding content) --
# scattered pellet frequency is reduced to compensate. Value is left
# untouched: the bonus cluster near one of the two goals is already this
# augment's own separate reward, not something to also boost here.
TWIN_GOAL_PELLET_FREQUENCY_MULTIPLIER = 0.7
TWIN_GOAL_PELLET_VALUE_MULTIPLIER     = 1.0

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
C_SPEED_BONUS = (100, 220, 255)  # distinct from C_PELLET, so a maze-clear time bonus reads as its own thing
C_DOOR_LOCKED   = (170, 70,  40)   # brick -- was (140,40,40), colliding with C_HAZARD/C_GOAL
C_DOOR_UNLOCKED = (60, 190, 170)   # teal -- was (90,180,90), colliding with C_PLAYER
C_SHIELD        = (190, 210, 230)  # pale blue/silver -- Bulwark's "Shielded!" popup, distinct from C_HAZARD's red
C_ROTATE_WARNING = (255, 200, 60)  # the rotating maze augment's pre-rotation warning arrow -- close to C_FLASH's urgency yellow

# Colored pellet variants -- deliberately distinct from C_PELLET/C_HAZARD/
# C_GOAL/C_PLAYER/C_SHIELD so each kind reads as its own thing at a glance.
C_PELLET_DOUBLE   = (60,  150, 255)  # vivid blue
C_PELLET_VOLATILE = (235, 100,  40)  # burnt orange-red -- distinct from C_HAZARD's red
C_PELLET_CHAIN    = (140, 230,  70)  # lime green -- distinct from C_PLAYER's green
C_PELLET_FREEZE   = (225, 245, 255)  # icy white-blue
C_PELLET_GAMBLE   = (150,  50, 210)  # violet purple -- distinct from C_GOAL's magenta

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

# Pressure pads (shifting_room.py): each pad drawn in its own colour
# (cycled by pad.color_index), same pattern as C_TELEPORT_PAIRS/
# C_DOOR_KEY_PAIRS -- there's no "partner" cell to pair it with (a pad's
# effect is an initially-invisible wall becoming floor, not a second
# marker), so this is just for telling multiple active pads apart at a
# glance. Earthy green/olive-leaning, distinct from both palettes above.
C_PRESSURE_PADS = [
    (150, 200, 90),
    (100, 180, 130),
    (190, 210, 80),
    (120, 160, 60),
]
