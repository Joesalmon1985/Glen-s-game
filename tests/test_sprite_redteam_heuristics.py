"""Heuristic sprite red-team tests (no Ollama / GPU required)."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from PIL import Image

from puca_dungeon.scene_compose import build_visual_spec, compose_image
from puca_dungeon.visual_catalog import DEFAULT_ASSETS_ROOT, iter_sprite_jobs, load_catalog
from scripts.sprite_redteam.fixtures import (
    all_fixtures,
    cell_state_variants,
    fixture_for_room,
    layout_delta_variants,
)
from scripts.sprite_redteam.heuristics import catalog_expect_size, judge_asset, judge_composition


class AssetHeuristicTests(unittest.TestCase):
    def test_kit_assets_pass_basic_heuristics_or_report(self):
        catalog = load_catalog()
        root = DEFAULT_ASSETS_ROOT
        for job in iter_sprite_jobs(catalog):
            path = root / job['file']
            expect = catalog_expect_size(catalog, job['kind'], {'size': job.get('size')})
            result = judge_asset(path, sprite_id=job['id'], kind=job['kind'], expect_size=expect)
            self.assertIsInstance(result.ok, bool)
            self.assertEqual(result.target, job['id'])
            if path.is_file():
                self.assertIn('size', result.metrics)

    def test_missing_asset_is_p0(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'missing.png'
            result = judge_asset(
                path, sprite_id='ghost', kind='prop', expect_size=(48, 48),
            )
            self.assertFalse(result.ok)
            self.assertTrue(any(f.severity == 'P0' for f in result.findings))

    def test_magenta_leftover_detected(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'cup.png'
            img = Image.new('RGBA', (48, 48), (255, 0, 255, 255))
            for x in range(10, 30):
                for y in range(10, 30):
                    img.putpixel((x, y), (200, 180, 160, 255))
            img.save(path)
            result = judge_asset(path, sprite_id='cup_full', kind='prop', expect_size=(48, 48))
            self.assertFalse(result.ok)
            self.assertTrue(any(f.invariant == 'chroma_clean' for f in result.findings))

    def test_solid_backdrop_fails_isolation(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'player.png'
            img = Image.new('RGBA', (72, 128), (180, 120, 140, 255))
            for x in range(20, 40):
                for y in range(20, 100):
                    img.putpixel((x, y), (0, 0, 0, 255))
            img.save(path)
            result = judge_asset(
                path, sprite_id='player_wary', kind='character', expect_size=(72, 128),
            )
            self.assertFalse(result.ok)
            invariants = {f.invariant for f in result.findings}
            self.assertTrue('isolation' in invariants or 'detail_palette' in invariants)


class FixtureSuiteTests(unittest.TestCase):
    def test_cell_variants_cover_prop_states(self):
        fixtures = cell_state_variants()
        ids = {fx.fixture_id for fx in fixtures}
        self.assertIn('cell_cup_empty', ids)
        self.assertIn('cell_slit_open', ids)
        self.assertIn('cell_bedding_floor', ids)
        empty = next(fx for fx in fixtures if fx.fixture_id == 'cell_cup_empty')
        spec = build_visual_spec(empty.world)
        layer_ids = {layer.sprite_id for layer in spec.layers}
        self.assertIn('cup_empty', layer_ids)
        self.assertTrue(empty.expected_sprite_ids <= layer_ids or 'cup_empty' in empty.expected_sprite_ids)

    def test_all_rooms_have_fixtures(self):
        catalog = load_catalog()
        fixtures = all_fixtures(catalog)
        rooms = {fx.room_id for fx in fixtures}
        for room_id in (catalog.get('layouts') or {}):
            self.assertIn(room_id, rooms)

    def test_composition_geometry_on_default_cell(self):
        catalog = load_catalog()
        fx = fixture_for_room('cell', staff_count=1, crowded=True)
        spec = build_visual_spec(fx.world, catalog)
        result = judge_composition(
            fixture_id=fx.fixture_id,
            room_id=fx.room_id,
            layers=spec.layers,
            catalog=catalog,
            expected_sprite_ids=fx.expected_sprite_ids,
        )
        self.assertEqual(result.kind, 'composition')
        # Expected sprites should match layers from build_visual_spec
        present = {layer.sprite_id for layer in spec.layers}
        self.assertFalse(fx.expected_sprite_ids - present)

    def test_off_canvas_flagged(self):
        catalog = load_catalog()
        fx = fixture_for_room('cell', staff_count=0, crowded=True)
        # Force player off canvas via layout override path in judge only:
        from puca_dungeon.scene_compose import SpriteLayer, SceneVisualSpec

        layers = [
            SpriteLayer('cell', 'background', (0, 0), 0),
            SpriteLayer('player_wary', 'character', (600, 600), 60),
        ]
        result = judge_composition(
            fixture_id='off_canvas',
            room_id='cell',
            layers=layers,
            catalog=catalog,
            expected_sprite_ids={'cell', 'player_wary'},
        )
        self.assertFalse(result.ok)
        self.assertTrue(any(f.invariant == 'on_canvas' for f in result.findings))

    def test_layout_delta_variants_include_current(self):
        slots = {'player': [240, 290], 'bed': [48, 300]}
        variants = layout_delta_variants(slots)
        names = [name for name, _ in variants]
        self.assertIn('current', names)
        self.assertGreater(len(variants), 1)

    def test_compose_fixture_png(self):
        catalog = load_catalog()
        fx = fixture_for_room('mess', staff_count=1, crowded=True)
        spec = build_visual_spec(fx.world, catalog)
        image = compose_image(spec, catalog, allow_placeholder=True)
        self.assertEqual(image.size, (512, 512))


if __name__ == '__main__':
    unittest.main()
