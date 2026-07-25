"""
history.py
----------
Persistent log of completed runs (dimensions, time solved, date), shown in
the right sidebar. Stored as JSON on disk so it survives between sessions.

Deliberately independent of pygame/Game so it can be loaded/saved/tested in
isolation.
"""

import json
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path

DEFAULT_HISTORY_PATH = Path(__file__).resolve().parent.parent / "run_history.json"


@dataclass(frozen=True)
class RunRecord:
    cols: int
    rows: int
    seconds: float
    finished_at: str  # ISO 8601 timestamp, e.g. "2026-07-25T14:03:11"

    @property
    def date_label(self) -> str:
        """Short human-readable date for display, e.g. '2026-07-25'."""
        return self.finished_at.split("T", 1)[0]


def new_record(cols: int, rows: int, seconds: float) -> RunRecord:
    return RunRecord(cols=cols, rows=rows, seconds=seconds, finished_at=datetime.now().isoformat(timespec="seconds"))


def load_history(path: Path = DEFAULT_HISTORY_PATH) -> list[RunRecord]:
    """Load past runs from disk. Returns an empty list if the file is missing or unreadable."""
    if not path.exists():
        return []
    try:
        raw = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return []
    records = []
    for entry in raw:
        try:
            records.append(RunRecord(**entry))
        except TypeError:
            continue  # skip malformed entries rather than fail the whole load
    return records


def save_history(records: list[RunRecord], path: Path = DEFAULT_HISTORY_PATH) -> None:
    path.write_text(json.dumps([asdict(r) for r in records], indent=2))


def append_record(records: list[RunRecord], record: RunRecord, path: Path = DEFAULT_HISTORY_PATH) -> list[RunRecord]:
    """Append `record`, persist to disk, and return the updated list (newest first)."""
    updated = [record] + list(records)
    save_history(updated, path)
    return updated
