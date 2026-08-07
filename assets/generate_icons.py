"""
generate_icons.py
------------------
Regenerates assets/icons/*.png -- extremely basic, hand-drawn 8x8 pixel art
for the entities that most needed a shape distinct from their neighbours
(key/door/gold all fell back to bare circles/rects before this, easy to
confuse at a glance -- see docs/assets.md). Each icon is a flat ASCII grid
below (one character per pixel) so the art itself stays readable as source,
rendered here into a real PNG via a pure-stdlib writer (struct + zlib only,
no PIL/pygame needed to *generate* these). sprites.py (which *loads* these at
runtime) still uses pygame, unaffected.

Run directly to regenerate every icon:
    python3 assets/generate_icons.py

Note: the .png files currently checked in under assets/icons/ were produced
by hand-transcribing these exact grids into ASCII-PPM (P3) data saved with a
.png extension, because the sandbox this was authored in couldn't execute
python/PIL/ImageMagick/etc. to run this script. SDL_image (which pygame's
image loader uses) detects format from file *content*, not extension, so
those PPM-content files load correctly today -- but they aren't real PNG
bytes. Running this script wherever python3 is available regenerates
byte-for-byte-identical-looking, but now genuinely PNG-encoded, files from
the same grids below; safe to do any time, purely a format upgrade.
"""

from __future__ import annotations

import struct
import zlib
from pathlib import Path

ICONS_DIR = Path(__file__).resolve().parent / "icons"

Color = tuple[int, int, int]

# Mirrors maze_game/constants.py's palette (kept as literals, not an import --
# assets/ is meant to stay a drop-in, code-independent directory per
# docs/assets.md, generator script included).
C_FLOOR = (20, 20, 35)
C_GOLD = (255, 150, 30)
C_GOLD_OUTLINE = (114, 67, 13)  # darken(C_GOLD, 0.45)
C_GOLD_SHINE = (255, 213, 165)  # lighten(C_GOLD, 0.6)
C_KEY = (225, 190, 80)
C_KEY_OUTLINE = (101, 85, 36)  # darken(C_KEY, 0.45)
C_DOOR_LOCKED = (170, 70, 40)
C_DOOR_LOCKED_OUTLINE = (76, 31, 18)  # darken(C_DOOR_LOCKED, 0.45)
C_DOOR_LOCKED_PLANK = (119, 49, 28)  # darken(C_DOOR_LOCKED, 0.7)
C_KEYHOLE = (25, 15, 10)
C_DOOR_UNLOCKED = (60, 190, 170)
C_DOOR_UNLOCKED_OUTLINE = (27, 85, 76)  # darken(C_DOOR_UNLOCKED, 0.45)
C_DOOR_UNLOCKED_PLANK = (42, 133, 119)  # darken(C_DOOR_UNLOCKED, 0.7)
C_HANDLE = (196, 235, 229)  # lighten(C_DOOR_UNLOCKED, 0.7)

# Every icon is opaque (no alpha) and filled with C_FLOOR as its "transparent"
# background -- entities only ever get drawn on open (floor) maze cells, so
# a flat floor-coloured background reads as see-through against the maze
# without needing per-pixel alpha at all.
GOLD = (
    {".": C_FLOOR, "O": C_GOLD_OUTLINE, "G": C_GOLD, "H": C_GOLD_SHINE},
    [
        "..OOOO..",
        ".OGGGGO.",
        "OGGHGGGO",
        "OGGGGGGO",
        "OGGGGGGO",
        "OGGGGGGO",
        ".OGGGGO.",
        "..OOOO..",
    ],
)

KEY = (
    {".": C_FLOOR, "O": C_KEY_OUTLINE, "K": C_KEY},
    [
        "OOO.....",
        "O.OKKKKK",
        "OOO....K",
        "........",
        "........",
        "........",
        "........",
        "........",
    ],
)

DOOR_LOCKED = (
    {"O": C_DOOR_LOCKED_OUTLINE, "D": C_DOOR_LOCKED, "P": C_DOOR_LOCKED_PLANK, "K": C_KEYHOLE},
    [
        "OOOOOOOO",
        "ODDDDDDO",
        "ODDDDDDO",
        "ODPPPPDO",
        "ODDKDDDO",
        "ODDDDDDO",
        "ODDDDDDO",
        "OOOOOOOO",
    ],
)

DOOR_UNLOCKED = (
    {"O": C_DOOR_UNLOCKED_OUTLINE, "D": C_DOOR_UNLOCKED, "P": C_DOOR_UNLOCKED_PLANK, "H": C_HANDLE},
    [
        "OOOOOOOO",
        "ODDDDDDO",
        "ODDDDDDO",
        "ODPPPPDO",
        "ODDHDDDO",
        "ODDDDDDO",
        "ODDDDDDO",
        "OOOOOOOO",
    ],
)

ICONS: dict[str, tuple[dict[str, Color], list[str]]] = {
    "gold": GOLD,
    "key": KEY,
    "door_locked": DOOR_LOCKED,
    "door_unlocked": DOOR_UNLOCKED,
}


def _chunk(tag: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)


def write_png(path: Path, pixels: list[list[Color]]) -> None:
    height = len(pixels)
    width = len(pixels[0])
    raw = bytearray()
    for row in pixels:
        raw.append(0)  # filter type: None, one byte per scanline
        for r, g, b in row:
            raw += bytes((r, g, b))
    compressed = zlib.compress(bytes(raw), 9)
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)  # 8-bit depth, colour type 2 (RGB)
    body = b"\x89PNG\r\n\x1a\n" + _chunk(b"IHDR", ihdr) + _chunk(b"IDAT", compressed) + _chunk(b"IEND", b"")
    path.write_bytes(body)


def render(palette: dict[str, Color], grid: list[str]) -> list[list[Color]]:
    return [[palette[ch] for ch in row] for row in grid]


if __name__ == "__main__":
    ICONS_DIR.mkdir(parents=True, exist_ok=True)
    for name, (palette, grid) in ICONS.items():
        write_png(ICONS_DIR / f"{name}.png", render(palette, grid))
        print(f"wrote {name}.png ({len(grid[0])}x{len(grid)})")
