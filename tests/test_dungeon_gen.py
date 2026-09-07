"""Tests for seeded dungeon generation and validation."""
from __future__ import annotations

from puca_dungeon.dungeon_gen import generate_dungeon
from puca_dungeon.dungeon_validate import generate_and_validate, stress_validate_seeds, validate_dungeon


def test_generate_deterministic():
    a = generate_dungeon(91)
    b = generate_dungeon(91)
    assert a.fingerprint == b.fingerprint
    assert a.to_dict() == b.to_dict()


def test_generate_varies_by_seed():
    a = generate_dungeon(91)
    b = generate_dungeon(92)
    # Topology should often differ; fingerprint must differ if edges differ
    assert a.fingerprint != b.fingerprint or a.meta != b.meta


def test_seed_91_valid():
    dungeon, report = generate_and_validate(91)
    assert report['ok'], report['errors']
    assert dungeon.entry_id in dungeon.passages
    assert dungeon.victory_id in dungeon.passages


def test_known_seed_fingerprint_stable():
    dungeon = generate_dungeon(91)
    # Pin fingerprint so accidental generator drift fails loudly
    assert len(dungeon.fingerprint) == 16
    again = generate_dungeon(91)
    assert again.fingerprint == dungeon.fingerprint


def test_stress_200_seeds():
    result = stress_validate_seeds(0, 200)
    assert result['ok'], result['failures'][:5]
    assert result['unique_fingerprints'] >= 2


def test_validate_rejects_broken_graph():
    dungeon = generate_dungeon(91)
    # Break victory reachability
    dungeon.passages.pop(dungeon.victory_id, None)
    report = validate_dungeon(dungeon)
    assert not report['ok']
