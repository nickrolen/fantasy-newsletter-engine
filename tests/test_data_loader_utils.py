"""Pure utility functions in data_loader: parsing, positions, atomic writes."""
import json

from modules.data_loader import (
    parse_record_string,
    get_position_list,
    classify_position_group,
    player_eligible_for_slot,
    normalize_manager_name,
    atomic_write_json,
    MANAGERS,
)


def test_parse_record_string():
    assert parse_record_string("(10-5)") == (10, 5)
    assert parse_record_string("10-5") == (10, 5)


def test_get_position_list():
    assert get_position_list("PG,SG,SF") == ["PG", "SG", "SF"]
    assert get_position_list("") == []


def test_classify_position_group_majority_vote():
    assert classify_position_group("PG,SG") == "G"
    assert classify_position_group("SF,PF") == "F"
    assert classify_position_group("C") == "C"


def test_player_eligible_for_slot():
    assert player_eligible_for_slot(["PG", "SG"], "G")
    assert player_eligible_for_slot(["C"], "UTIL")
    assert not player_eligible_for_slot(["C"], "G")


def test_normalize_manager_name_aliases():
    for m in MANAGERS:
        assert normalize_manager_name(m.lower()) == m


def test_atomic_write_json_leaves_no_tmp(tmp_path):
    target = tmp_path / "state.json"
    atomic_write_json(target, {"hello": [1, 2, 3]})
    assert json.load(open(target, encoding="utf-8")) == {"hello": [1, 2, 3]}
    assert not list(tmp_path.glob("*.tmp"))
    # Overwrite is atomic too
    atomic_write_json(target, {"hello": "again"})
    assert json.load(open(target, encoding="utf-8")) == {"hello": "again"}
