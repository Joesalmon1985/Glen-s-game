"""Tests for facility sprite catalog + scene compositor (graphics only)."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from puca_dungeon.facility_models import make_initial_facility
from puca_dungeon.ff_rules import make_adventure_sheet
from puca_dungeon.models import WorldState
from puca_dungeon.resolve import Resolution
from puca_dungeon.rng import GameRNG
from puca_dungeon.scene_compose import build_visual_spec, compose_facility_scene
from puca_dungeon.visual_catalog import dump_facility_draft, iter_sprite_jobs, jobs_for_room, load_catalog


class SpriteCatalogTests(unittest.TestCase):
    def test_catalog_covers_facility_rooms(self):
        cat = load_catalog()
        layouts = cat.get('layouts') or {}
        for room_id in (
            'cell', 'corridor', 'washroom', 'mess', 'interview',
            'prep', 'heaven', 'hell', 'research_quarters',
        ):
            self.assertIn(room_id, layouts)
            self.assertIn(room_id, cat.get('backgrounds') or {})

    def test_iter_jobs_non_empty(self):
        jobs = iter_sprite_jobs()
        self.assertGreaterEqual(len(jobs), 30)
        kinds = {job['kind'] for job in jobs}
        self.assertEqual(kinds, {'background', 'prop', 'character'})

    def test_dump_draft_matches_facility_rooms(self):
        draft = dump_facility_draft()
        room_ids = {row['id'] for row in draft['rooms']}
        self.assertIn('cell', room_ids)
        self.assertIn('hell', room_ids)
        entity_ids = {row['id'] for row in draft['entities']}
        self.assertIn('cup', entity_ids)
        self.assertIn('door', entity_ids)

    def test_jobs_for_room_cell(self):
        jobs = jobs_for_room('cell')
        ids = {job['id'] for job in jobs}
        self.assertIn('cell', ids)
        self.assertTrue(any(i.startswith('cup_') for i in ids))
        self.assertTrue(any(i.startswith('player_') for i in ids))


class SceneComposeTests(unittest.TestCase):
    def _world(self) -> WorldState:
        rng = GameRNG.from_seed(91)
        fac = make_initial_facility(rng)
        sheet = make_adventure_sheet(rng)
        return WorldState(sheet=sheet, facility=fac, mode='facility', passage_id=0)

    def test_cell_includes_core_props_and_player(self):
        world = self._world()
        spec = build_visual_spec(world)
        ids = [layer.sprite_id for layer in spec.layers]
        self.assertEqual(spec.room_id, 'cell')
        self.assertIn('cell', ids)  # background key
        self.assertIn('player_wary', ids)
        # Default bed/door/cup/book are already painted into the cell background.
        self.assertFalse(any(sid.startswith('cup_') for sid in ids))
        self.assertFalse(any(sid.startswith('book_') for sid in ids))
        self.assertFalse(any(sid.startswith('door_') for sid in ids))
        self.assertNotIn('bed', ids)

    def test_state_change_overlays_baked_props(self):
        world = self._world()
        cup = world.facility.entity('cup')
        cup.state['has_water'] = False
        world.facility.entities['cup'] = cup.to_dict()
        world.facility.slit_open = True
        door = world.facility.entity('door')
        door.state['slit_open'] = True
        world.facility.entities['door'] = door.to_dict()
        ids = [layer.sprite_id for layer in build_visual_spec(world).layers]
        self.assertIn('cup_empty', ids)
        self.assertNotIn('door_slit_open', ids)

    def test_chroma_key_strips_magenta_fringe(self):
        from PIL import Image
        from puca_dungeon.scene_compose import chroma_key_magenta
        img = Image.new('RGBA', (8, 8), (255, 0, 255, 255))
        img.putpixel((3, 3), (40, 80, 40, 255))
        img.putpixel((4, 3), (220, 60, 200, 255))
        out = chroma_key_magenta(img)
        self.assertEqual(out.getpixel((0, 0))[3], 0)
        self.assertEqual(out.getpixel((3, 3))[3], 255)
        self.assertEqual(out.getpixel((4, 3))[3], 0)

    def test_book_dungeon_presentation_is_printed_not_cell(self):
        from puca_dungeon.portrait.present import compose_facility_presentation, presentation_fingerprint
        world = self._world()
        world.mode = 'book_dungeon'
        world.passage_id = 1
        self.assertTrue(presentation_fingerprint(world).startswith('sprite:printed:'))
        with tempfile.TemporaryDirectory() as folder:
            kind, path = compose_facility_presentation(world, Path(folder))
            self.assertEqual(kind, 'printed')
            self.assertTrue(path.is_file())
            from PIL import Image
            with Image.open(path) as image:
                self.assertEqual(image.size, (512, 512))

    def test_cup_empty_and_slit_change_fingerprint(self):
        world = self._world()
        before = build_visual_spec(world).key
        cup = world.facility.entity('cup')
        cup.state['has_water'] = False
        world.facility.entities['cup'] = cup.to_dict()
        mid = build_visual_spec(world).key
        self.assertNotEqual(before, mid)
        ids = [layer.sprite_id for layer in build_visual_spec(world).layers]
        self.assertIn('cup_empty', ids)

    def test_staff_present_adds_character_layer(self):
        world = self._world()
        world.facility.staff_present = True
        world.facility.staff_count = 1
        world.facility.arc.present_ids = ['orderly_quiet']
        ids = [layer.sprite_id for layer in build_visual_spec(world).layers]
        self.assertTrue(any(sid.startswith('staff_') for sid in ids))

    def test_compose_writes_512_png_with_placeholders(self):
        world = self._world()
        with tempfile.TemporaryDirectory() as folder:
            spec, path = compose_facility_scene(world, Path(folder), allow_placeholder=True)
            self.assertTrue(path.is_file())
            from PIL import Image
            with Image.open(path) as image:
                self.assertEqual(image.size, (512, 512))
                self.assertEqual(image.format, 'PNG')
            # Cache hit
            spec2, path2 = compose_facility_scene(world, Path(folder), allow_placeholder=True)
            self.assertEqual(spec.key, spec2.key)
            self.assertEqual(path, path2)

    def test_asset_stamp_changes_fingerprint_when_png_replaced(self):
        world = self._world()
        before = build_visual_spec(world).key
        from puca_dungeon.visual_catalog import DEFAULT_ASSETS_ROOT
        player = DEFAULT_ASSETS_ROOT / 'characters' / 'player_wary.png'
        self.assertTrue(player.is_file())
        original = player.read_bytes()
        try:
            from PIL import Image
            img = Image.open(player).convert('RGBA')
            pixels = img.load()
            r, g, b, a = pixels[0, 0]
            pixels[0, 0] = (r, g, b, a)
            tmp = player.with_suffix('.tmp.png')
            img.putpixel((1, 1), pixels[1, 1])
            img.save(tmp, format='PNG')
            tmp.replace(player)
            after = build_visual_spec(world).key
            self.assertNotEqual(before, after)
        finally:
            player.write_bytes(original)
            self.assertTrue(player.is_file())

    def test_debug_overlay_composes(self):
        world = self._world()
        with tempfile.TemporaryDirectory() as folder:
            _spec, path = compose_facility_scene(
                world, Path(folder), allow_placeholder=True, debug_layers=True,
            )
            self.assertTrue(path.name.endswith('_dbg.png'))
            from PIL import Image
            with Image.open(path) as image:
                self.assertEqual(image.size, (512, 512))

    def test_image_decision_uses_sprite_renderer(self):
        from puca_dungeon.image_prompt import image_decision
        world = self._world()
        img = image_decision(world, Resolution(image_dirty=True))
        self.assertEqual(img.get('renderer'), 'sprites')
        self.assertTrue(str(img.get('full_prompt') or '').startswith('sprite:'))
        again = image_decision(world, Resolution(image_dirty=False))
        self.assertEqual(again.get('decision'), 'REUSE')

    def test_book_dungeon_image_decision_stays_on_sprites(self):
        from puca_dungeon.image_prompt import image_decision
        world = self._world()
        world.mode = 'book_dungeon'
        img = image_decision(world, Resolution(image_dirty=True))
        self.assertEqual(img.get('renderer'), 'sprites')
        self.assertTrue(str(img.get('full_prompt') or '').startswith('sprite:printed:'))


if __name__ == '__main__':
    unittest.main()
