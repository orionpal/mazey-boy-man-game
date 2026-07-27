"""
Tests for maze_game.progression.shop.items -- Item/Loadout in isolation, no
LabyrinthRun needed (the actual wall-break/laser/stopwatch/squeak *effects*
are exercised at the LabyrinthRun level in tests/progression/test_run.py --
this file only covers the shared charge bookkeeping).
"""

from maze_game.progression.shop.items import Item, Loadout, ALL_ITEMS, UNLIMITED_ITEM_IDS


def test_loadout_starts_with_no_picks_or_charges():
    loadout = Loadout()
    assert loadout.picks == {}
    assert loadout.charges == {}


def test_acquiring_an_item_records_the_pick_and_grants_a_charge():
    loadout = Loadout()
    item = Item(id="wall_breaker", name="Wall Breaker", description="d", slot_key="Q")
    loadout.acquire(item)
    assert loadout.picks == {"wall_breaker": 1}
    assert loadout.charges == {"wall_breaker": 1}


def test_acquiring_the_same_item_twice_stacks_charges():
    loadout = Loadout()
    item = Item(id="laser", name="Laser", description="d", slot_key="W")
    loadout.acquire(item)
    loadout.acquire(item)
    assert loadout.picks == {"laser": 2}
    assert loadout.charges == {"laser": 2}


def test_squeaky_toy_never_gets_a_charge_entry():
    loadout = Loadout()
    item = Item(id="squeaky_toy", name="Squeaky Toy", description="d", slot_key="R")
    loadout.acquire(item)
    loadout.acquire(item)
    assert loadout.picks == {"squeaky_toy": 2}
    assert loadout.charges == {}


def test_consume_charge_decrements_and_returns_true_when_available():
    loadout = Loadout()
    loadout.acquire(Item(id="stopwatch", name="Stopwatch", description="d", slot_key="E"))
    assert loadout.consume_charge("stopwatch") is True
    assert loadout.charges["stopwatch"] == 0


def test_consume_charge_returns_false_when_none_available():
    loadout = Loadout()
    assert loadout.consume_charge("wall_breaker") is False  # never acquired
    loadout.acquire(Item(id="wall_breaker", name="Wall Breaker", description="d", slot_key="Q"))
    loadout.consume_charge("wall_breaker")
    assert loadout.consume_charge("wall_breaker") is False  # exhausted


def test_all_items_have_distinct_ids_and_slot_keys():
    ids = [i.id for i in ALL_ITEMS]
    slots = [i.slot_key for i in ALL_ITEMS]
    assert len(ids) == len(set(ids))
    assert len(slots) == len(set(slots))
    assert set(slots) == {"Q", "W", "E", "R"}


def test_unlimited_item_ids_are_a_subset_of_all_items():
    ids = {i.id for i in ALL_ITEMS}
    assert UNLIMITED_ITEM_IDS <= ids
