"""
constants.py
------------
All tuneable game settings live here. Change values in this file to
customise the look and feel without touching game logic.
"""

# ── Grid dimensions (must be odd for the DFS maze carver) ────────────────
COLS = 13
ROWS = 13

# ── Display ───────────────────────────────────────────────────────────────
CELL   = 28          # pixels per maze cell
WIDTH  = COLS * CELL
HEIGHT = ROWS * CELL + 60   # +60 px for the HUD bar at the bottom
FPS    = 60

# ── Colours  (R, G, B) ────────────────────────────────────────────────────
C_BG     = (15,  15,  25)
C_WALL   = (40,  80, 140)
C_FLOOR  = (20,  20,  35)
C_PLAYER = (80, 220, 120)
C_GOAL   = (220, 80,  80)
C_TEXT   = (220, 220, 220)
C_DIM    = (100, 100, 120)
C_FLASH  = (255, 220,  60)
C_HUD_BG = (10,  10,  20)
