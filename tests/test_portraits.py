"""Layered portrait renderer, manifests, bake-off, and presentation cues."""
from __future__ import annotations

import copy
import hashlib
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from puca_dungeon.conversation import set_interlocutor
from puca_dungeon.facility_models import make_initial_facility
from puca_dungeon.facility_react import _set_presence
from puca_dungeon.ff_rules import make_adventure_sheet
from puca_dungeon.models import WorldState
from puca_dungeon.portrait.assignments import clear_assignment_cache
from puca_dungeon.portrait.bakeoff import STANDARD_POSES, gallery_label
from puca_dungeon.portrait.cues import portrait_cue_from_world
from puca_dungeon.portrait.errors import PortraitError
from puca_dungeon.portrait.manifest import (
    CANVAS_SIZE,
    FACE_PROFILE_IDS,
    load_manifest,
    portraits_root,
)
from puca_dungeon.portrait.render import clear_render_cache, render_portrait
from puca_dungeon.portrait.types import BrowState, EyeState, FacePose, Gaze, MouthState
from puca_dungeon.portrait_gallery import FORBIDDEN_LABEL_WORDS
from puca_dungeon.rng import GameRNG
from puca_dungeon.scene_compose import build_visual_spec


def _digest(image) -> str:
    return hashlib.sha256(image.convert('RGBA').tobytes()).hexdigest()


def _world() -> WorldState:
    rng = GameRNG.from_seed(91)
    fac = make_initial_facility(rng)
    sheet = make_adventure_sheet(rng)
    return WorldState(sheet=sheet, facility=fac, mode='facility', passage_id=0)


class ManifestTests(unittest.TestCase):
    def test_all_five_manifests_load(self):
        for pid in FACE_PROFILE_IDS:
            data = load_manifest(pid)
            self.assertEqual(data['visual_profile_id'], pid)
            self.assertEqual(int(data['canvas']['width']), CANVAS_SIZE[0])
            self.assertEqual(int(data['canvas']['height']), CANVAS_SIZE[1])

    def test_required_files_exist_canonical_rgba(self):
        root = portraits_root()
        for pid in FACE_PROFILE_IDS:
            manifest = load_manifest(pid)
            folder = root / pid
            files = list(folder.rglob('*.png'))
            self.assertGreaterEqual(len(files), 20, pid)
            z_order = manifest['_z_order']
            self.assertIn('head', z_order)
            identity = manifest['identity']
            expressions = manifest['expressions']
            rels = [identity['head']]
            rels.extend(expressions['eyes'].values())
            rels.extend(expressions['gaze'].values())
            rels.extend(expressions['mouths'].values())
            rels.extend(expressions['brows']['left'].values())
            rels.extend(expressions['brows']['right'].values())
            for rel in rels:
                path = folder / rel
                self.assertTrue(path.is_file(), path)
                with Image.open(path) as img:
                    self.assertEqual(img.size, CANVAS_SIZE, path)
                    self.assertEqual(img.mode, 'RGBA', path)
                    extrema = img.getextrema()
                    self.assertEqual(len(extrema), 4)
                    self.assertLess(extrema[3][0], 255, msg=f'{path} should have transparency')

    def test_z_order_valid(self):
        for pid in FACE_PROFILE_IDS:
            manifest = load_manifest(pid)
            names = manifest['_z_order']
            self.assertEqual(len(names), len(set(names)))
            self.assertIn('head', names)
            self.assertIn('irises', names)
            self.assertIn('mouth', names)

    def test_unknown_profile_fails_clearly(self):
        with self.assertRaises(PortraitError) as ctx:
            load_manifest('not_a_face')
        self.assertIn('not_a_face', str(ctx.exception))

    def test_path_injection_rejected(self):
        with self.assertRaises(PortraitError):
            load_manifest('../secrets')


class RenderTests(unittest.TestCase):
    def test_five_neutrals_render_and_differ(self):
        digests = []
        for pid in FACE_PROFILE_IDS:
            img = render_portrait(pid, FacePose())
            self.assertEqual(img.size, CANVAS_SIZE)
            self.assertEqual(img.mode, 'RGBA')
            digests.append(_digest(img))
        self.assertEqual(len(set(digests)), 5)

    def test_expression_changes_pixels(self):
        base = _digest(render_portrait('face_001', FacePose()))
        smile = _digest(render_portrait('face_001', FacePose(mouth=MouthState.SMILE)))
        closed = _digest(render_portrait('face_001', FacePose(eye_openness=EyeState.CLOSED)))
        left = _digest(render_portrait('face_001', FacePose(gaze=Gaze.LEFT)))
        right = _digest(render_portrait('face_001', FacePose(gaze=Gaze.RIGHT)))
        raised = _digest(render_portrait('face_001', FacePose(
            left_brow=BrowState.RAISED, right_brow=BrowState.RAISED,
        )))
        self.assertNotEqual(base, smile)
        self.assertNotEqual(base, closed)
        self.assertNotEqual(left, right)
        self.assertNotEqual(base, raised)
        open_d = _digest(render_portrait('face_002', FacePose(eye_openness=EyeState.OPEN)))
        closed_d = _digest(render_portrait('face_002', FacePose(eye_openness=EyeState.CLOSED)))
        self.assertNotEqual(open_d, closed_d)
        mouth_n = _digest(render_portrait('face_003', FacePose(mouth=MouthState.NEUTRAL)))
        mouth_s = _digest(render_portrait('face_003', FacePose(mouth=MouthState.SMALL_SMILE)))
        self.assertNotEqual(mouth_n, mouth_s)
        brow_n = _digest(render_portrait('face_004', FacePose()))
        brow_r = _digest(render_portrait('face_004', FacePose(left_brow=BrowState.RAISED)))
        self.assertNotEqual(brow_n, brow_r)

    def test_identical_inputs_identical_pixels(self):
        a = render_portrait('face_005', FacePose(gaze=Gaze.UP, mouth=MouthState.UNEASY))
        b = render_portrait('face_005', FacePose(gaze=Gaze.UP, mouth=MouthState.UNEASY))
        self.assertEqual(_digest(a), _digest(b))

    def test_invalid_pose_falls_back_to_neutral_fields(self):
        pose = FacePose.coerce({'eye_openness': 'nope', 'gaze': 'sideways', 'mouth': 'grin'})
        self.assertEqual(pose.eye_openness, EyeState.OPEN)
        self.assertEqual(pose.gaze, Gaze.FORWARD)
        self.assertEqual(pose.mouth, MouthState.NEUTRAL)
        img = render_portrait('face_001', pose)
        self.assertEqual(img.size, CANVAS_SIZE)

    def test_unknown_id_render_fails(self):
        with self.assertRaises(PortraitError):
            render_portrait('face_999')

    def test_render_does_not_mutate_world(self):
        world = _world()
        before = copy.deepcopy(world.to_dict())
        render_portrait('face_001', FacePose())
        portrait_cue_from_world(world)
        self.assertEqual(world.to_dict(), before)

    def test_closed_eyes_omit_iris_difference_from_gaze(self):
        closed_left = render_portrait('face_001', FacePose(
            eye_openness=EyeState.CLOSED, gaze=Gaze.LEFT,
        ))
        closed_right = render_portrait('face_001', FacePose(
            eye_openness=EyeState.CLOSED, gaze=Gaze.RIGHT,
        ))
        self.assertEqual(_digest(closed_left), _digest(closed_right))


class GalleryTests(unittest.TestCase):
    def test_labels_are_anonymous(self):
        for pid in FACE_PROFILE_IDS:
            label = gallery_label(pid)
            low = label.lower()
            self.assertTrue(label.startswith('FACE'))
            for word in FORBIDDEN_LABEL_WORDS:
                self.assertNotIn(word, low)
        self.assertEqual(len(STANDARD_POSES), 11)

    def test_export_contact_sheets(self):
        from puca_dungeon.portrait.bakeoff import export_contact_sheets
        with tempfile.TemporaryDirectory() as folder:
            written = export_contact_sheets(Path(folder))
            names = {path.name for path in written}
            self.assertIn('face_bakeoff_all_neutral.png', names)
            for digits in ('001', '002', '003', '004', '005'):
                self.assertIn(f'face_bakeoff_expressions_{digits}.png', names)
            for path in written:
                with Image.open(path) as img:
                    self.assertEqual(img.format, 'PNG')
                    self.assertGreater(img.size[0], 100)


class PresenceAndCueTests(unittest.TestCase):
    def setUp(self):
        clear_assignment_cache()

    def test_empty_presence_player_only(self):
        world = _world()
        world.facility.arc.present_ids = []
        world.facility.staff_present = False
        world.facility.staff_count = 0
        ids = [layer.sprite_id for layer in build_visual_spec(world).layers]
        self.assertTrue(any(sid.startswith('player_') for sid in ids))
        self.assertFalse(any(sid.startswith('body_') or sid.startswith('staff_') for sid in ids))

    def test_subjects_do_not_use_placeholder_bodies(self):
        world = _world()
        world.facility.arc.present_ids = ['iven', 'nessa']
        ids = [layer.sprite_id for layer in build_visual_spec(world).layers]
        self.assertNotIn('body_001', ids)
        self.assertNotIn('body_002', ids)
        self.assertTrue(any(sid.startswith('player_') for sid in ids))

    def test_staff_bodies_still_appear(self):
        world = _world()
        world.facility.arc.present_ids = ['orderly_quiet', 'orderly_anxious']
        ids = [layer.sprite_id for layer in build_visual_spec(world).layers]
        self.assertIn('staff_orderly', ids)
        self.assertIn('staff_anxious', ids)

    def test_slot_cap_does_not_crash(self):
        world = _world()
        world.facility.arc.present_ids = [
            'iven', 'nessa', 'ruan', 'orderly_quiet', 'orderly_anxious', 'attendant_a',
        ]
        spec = build_visual_spec(world)
        bodies = [layer for layer in spec.layers if layer.kind == 'character' and not layer.sprite_id.startswith('player_')]
        self.assertLessEqual(len(bodies), 4)

    def test_cue_visible_when_assigned_interlocutor_present(self):
        world = _world()
        world.facility.arc.present_ids = ['iven']
        set_interlocutor(world.facility, 'iven')
        cue = portrait_cue_from_world(world)
        self.assertTrue(cue.visible)
        self.assertEqual(cue.visual_profile_id, 'face_001')
        self.assertEqual(cue.focus_reason, 'dialogue')

    def test_cue_falls_back_to_profiled_present_npc(self):
        world = _world()
        world.facility.arc.present_ids = ['orderly_quiet', 'iven']
        set_interlocutor(world.facility, 'orderly_quiet')
        cue = portrait_cue_from_world(world)
        self.assertTrue(cue.visible)
        self.assertEqual(cue.character_id, 'iven')
        self.assertEqual(cue.visual_profile_id, 'face_001')
        self.assertEqual(cue.focus_reason, 'dialogue_group')
        world = _world()
        world.facility.arc.present_ids = ['iven']
        cue = portrait_cue_from_world(world)
        self.assertFalse(cue.visible)

    def test_leaving_clears_interlocutor_and_cue(self):
        world = _world()
        world.facility.arc.present_ids = ['iven']
        set_interlocutor(world.facility, 'iven')
        _set_presence(world.facility, [])
        self.assertNotIn('iven', world.facility.arc.present_ids)
        conv = world.facility.arc.conversation or {}
        self.assertFalse(conv.get('interlocutor_id'))
        cue = portrait_cue_from_world(world)
        self.assertFalse(cue.visible)

    def test_live_presentation_stays_on_the_room(self):
        from puca_dungeon.portrait.present import compose_facility_presentation, presentation_fingerprint
        world = _world()
        world.facility.arc.present_ids = ['iven']
        before = presentation_fingerprint(world)
        set_interlocutor(world.facility, 'iven')
        after = presentation_fingerprint(world)
        self.assertEqual(before, after)
        self.assertNotIn('portrait', after)
        with tempfile.TemporaryDirectory() as folder:
            kind, path = compose_facility_presentation(world, Path(folder))
            self.assertEqual(kind, 'scene')
            self.assertTrue(path.is_file())


if __name__ == '__main__':
    unittest.main()
