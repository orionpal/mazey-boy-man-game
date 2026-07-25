"""Tests for maze_game.history — run-log persistence."""

from maze_game.history import RunRecord, new_record, load_history, save_history, append_record


def test_load_history_missing_file_returns_empty_list(tmp_path):
    assert load_history(tmp_path / "does_not_exist.json") == []


def test_save_then_load_round_trips(tmp_path):
    path = tmp_path / "history.json"
    records = [
        RunRecord(cols=21, rows=21, seconds=12.34, finished_at="2026-07-24T10:00:00"),
        RunRecord(cols=31, rows=31, seconds=45.6, finished_at="2026-07-25T09:30:00"),
    ]
    save_history(records, path)
    assert load_history(path) == records


def test_load_history_skips_malformed_entries(tmp_path):
    path = tmp_path / "history.json"
    path.write_text('[{"cols": 21, "rows": 21, "seconds": 1.0, "finished_at": "x"}, {"bad": "entry"}]')
    loaded = load_history(path)
    assert len(loaded) == 1
    assert loaded[0].cols == 21


def test_load_history_handles_corrupt_json(tmp_path):
    path = tmp_path / "history.json"
    path.write_text("not valid json{{{")
    assert load_history(path) == []


def test_append_record_persists_and_prepends_newest_first(tmp_path):
    path = tmp_path / "history.json"
    first = new_record(21, 21, 10.0)
    updated = append_record([], first, path)
    assert updated == [first]

    second = new_record(31, 31, 20.0)
    updated = append_record(updated, second, path)
    assert updated == [second, first]
    assert load_history(path) == [second, first]


def test_new_record_finished_at_is_iso_format():
    record = new_record(21, 21, 5.0)
    # Should parse as ISO 8601 without raising, and date_label should be the date portion.
    from datetime import datetime

    datetime.fromisoformat(record.finished_at)
    assert record.date_label == record.finished_at.split("T")[0]
