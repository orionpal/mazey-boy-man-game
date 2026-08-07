"""
deploy_web.py
-------------
Builds the pygbag WebAssembly bundle for this game and copies it into the
orionpal.com website's public/mazey-boy/ directory, ready to commit there.

Does the same thing that used to be done by hand every time the web build
needed updating: stage a clean copy of just the shipped source (main.py,
maze_game/, assets/ -- not tests/docs/.venv/build artifacts, which pygbag
would otherwise happily bundle up too), run pygbag against that staging
copy (not this repo's own working directory, so nothing here gets
touched), and drop the result into the site repo.

Usage:
    python3 deploy_web.py [--site-dir PATH]

Requires this repo's .venv to exist already (see README's "Getting
Started"); installs pygbag into it automatically if missing.

Deliberately does NOT commit or push anything in either repo -- review the
diff (this script prints `git status` for the site directory when it's
done) and commit/push yourself, same as any other change.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent
VENV_PYTHON = REPO_ROOT / ".venv" / "bin" / "python3"
DEFAULT_SITE_MAZEY_BOY_DIR = REPO_ROOT.parent / "orionpal.com" / "public" / "mazey-boy"

# What actually ships in the web build -- everything else (tests/, docs/,
# gold.json, run_history.json, ...) either doesn't belong in a build
# artifact or is desktop-only save data with no web equivalent yet.
SOURCE_ITEMS = ["main.py", "maze_game", "assets"]


def _ensure_pygbag(python: Path) -> None:
    check = subprocess.run([str(python), "-c", "import pygbag"], capture_output=True)
    if check.returncode == 0:
        return
    print("pygbag not found in .venv -- installing (one-time)...")
    subprocess.run([str(python), "-m", "pip", "install", "--quiet", "pygbag"], check=True)


def _stage_source(staging_dir: Path) -> None:
    for item in SOURCE_ITEMS:
        src = REPO_ROOT / item
        dst = staging_dir / item
        if src.is_dir():
            shutil.copytree(src, dst, ignore=shutil.ignore_patterns("__pycache__"))
        else:
            shutil.copy2(src, dst)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--site-dir", type=Path, default=DEFAULT_SITE_MAZEY_BOY_DIR,
        help=f"orionpal.com's public/mazey-boy directory to write into (default: {DEFAULT_SITE_MAZEY_BOY_DIR})",
    )
    args = parser.parse_args()

    if not VENV_PYTHON.exists():
        sys.exit(
            f"No .venv found at {VENV_PYTHON} -- create one first:\n"
            "    python3 -m venv .venv && .venv/bin/pip install -r requirements.txt"
        )
    if not args.site_dir.parent.exists():
        sys.exit(
            f"Site directory's parent doesn't exist: {args.site_dir.parent}\n"
            "Is orionpal.com cloned as a sibling of this repo? Pass --site-dir to point elsewhere."
        )

    _ensure_pygbag(VENV_PYTHON)

    with tempfile.TemporaryDirectory(prefix="mazey-boy-web-build-") as tmp:
        # pygbag derives the bundle's internal name (and shipped filenames)
        # from its target directory's name -- "mazey-boy" here keeps that
        # name clean instead of leaking a random temp-dir name into it.
        staging_dir = Path(tmp) / "mazey-boy"
        staging_dir.mkdir()
        print(f"Staging clean source into {staging_dir} ...")
        _stage_source(staging_dir)

        print("Building with pygbag (this fetches the CPython/pygame-ce web runtime the first time, ~1-2 min)...")
        subprocess.run(
            [str(VENV_PYTHON), "-m", "pygbag", "--build", "main.py"],
            cwd=staging_dir, check=True,
        )

        build_output = staging_dir / "build" / "web"
        if not build_output.is_dir():
            sys.exit(f"pygbag build didn't produce {build_output} -- see its output above for what went wrong.")

        print(f"Copying build output into {args.site_dir} ...")
        if args.site_dir.exists():
            shutil.rmtree(args.site_dir)
        shutil.copytree(build_output, args.site_dir)

    print(f"\nDone. Changes in {args.site_dir}:")
    site_repo_root = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"], cwd=args.site_dir, capture_output=True, text=True, check=True,
    ).stdout.strip()
    subprocess.run(["git", "status", "--short", str(args.site_dir)], cwd=site_repo_root)
    print(
        "\nNothing has been committed or pushed. Review the diff above, then commit + push "
        "orionpal.com (and this repo too, if the game source itself changed) yourself."
    )


if __name__ == "__main__":
    main()
