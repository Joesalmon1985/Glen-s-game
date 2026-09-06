"""Encounter 1: stone table with six locked boxes (source-derived)."""
from __future__ import annotations

from puca_dungeon.models import BoxId, BoxState, EncounterId, PlayerState, WorldState


OTHER_LABELS = [
    ('box_a', "Ashen's box"),
    ('box_b', "Bram's box"),
    ('box_c', "Cora's box"),
    ('box_d', "Drek's box"),
    ('box_e', "Elira's box"),
]


def make_opening_world(player_name: str = 'Adventurer', seed_note: str = '') -> WorldState:
    name = (player_name or 'Adventurer').strip()[:40] or 'Adventurer'
    boxes = {
        BoxId.PLAYER.value: BoxState(
            id=BoxId.PLAYER.value,
            label=f"{name}'s box",
            is_player_box=True,
        ),
    }
    for box_id, label in OTHER_LABELS:
        boxes[box_id] = BoxState(id=box_id, label=label, is_player_box=False)

    world = WorldState(
        encounter=EncounterId.WALK_BOXES.value,
        player=PlayerState(name=name, location=EncounterId.WALK_BOXES.value),
        boxes=boxes,
        visible_entities=[
            'stone_table', 'six_locked_boxes', 'passage_ahead', 'passage_behind',
            BoxId.PLAYER.value, *[b for b, _ in OTHER_LABELS], 'trial_key_player',
        ],
        flags={'opening_narrated': False, 'seed_note': seed_note},
    )
    return world


def public_perception(world: WorldState) -> dict:
    """What the interpreter may see — no hidden traps, private flags, or menus."""
    boxes = []
    for box in world.boxes.values():
        info = {
            'id': box.id,
            'label': box.label,
            'is_named_for_player': box.is_player_box,
            'open': box.open,
            'locked': box.locked and not box.open,
            'destroyed': box.destroyed,
        }
        if box.trap_discovered:
            info['trap_visible'] = True
            info['trap_disabled'] = box.trap_disabled
            info['trap_fired'] = box.trap_fired
        boxes.append(info)

    perception = {
        'encounter': world.encounter,
        'location_description': (
            'A stone table holds six locked boxes. One bears your name. '
            'A passage continues deeper into the dungeon behind the table; '
            'the entrance tunnel lies the way you came.'
            if world.encounter == EncounterId.WALK_BOXES.value
            else (
                'A junction: a white arrow painted on the wall points west. '
                'Passages lead west and right. The floor is dusty.'
                + (' Tracks are visible in the dust.' if world.junction_inspected else '')
            )
        ),
        'player': {
            'name': world.player.name,
            'hp': world.player.hp if world.player.hp < world.player.max_hp else None,
            'alive': world.player.alive,
            'inventory_visible': list(world.player.inventory),
            'known': list(world.player.knowledge),
        },
        'boxes': boxes if world.encounter == EncounterId.WALK_BOXES.value else [],
        'visible_entities': list(world.visible_entities),
    }
    # Pursuer only if perceptible
    if world.pursuer.state == 'approaching':
        perception['heard'] = ['distant_footsteps_behind']
    elif world.pursuer.state == 'close':
        perception['heard'] = ['close_footsteps_behind']
    elif world.pursuer.state in ('present', 'hostile', 'allied'):
        perception['present_npcs'] = [{
            'id': 'challenger',
            'name': world.pursuer.name,
            'kind': world.pursuer.kind,
            'disposition': world.pursuer.disposition,
            'visible': True,
        }]
    return perception


OPENING_PROSE = (
    "You enter Deathtrap Dungeon after the other contestants. Baron Sukumvit's "
    "servant pressed a single iron key into your hand. After roughly five minutes "
    "of cautious travel, the passage widens around a stone table. Six locked boxes "
    "rest upon it. One bears your name."
)
