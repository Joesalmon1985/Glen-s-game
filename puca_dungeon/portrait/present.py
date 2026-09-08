"""Choose room composite vs dialogue portrait for the art panel."""
from __future__ import annotations

from pathlib import Path
from typing import Optional


def presentation_fingerprint(world) -> str:
    from puca_dungeon.scene_compose import book_dungeon_visual_key, build_visual_spec

    if str(getattr(world, 'mode', '') or '') == 'book_dungeon':
        return f'sprite:printed:{book_dungeon_visual_key(world)}'
    spec = build_visual_spec(world)
    return f'sprite:{spec.key}'


def compose_facility_presentation(
    world,
    cache_dir: Path,
    catalog=None,
    root: Optional[Path] = None,
    allow_placeholder: bool = True,
    debug_layers: Optional[bool] = None,
) -> tuple[str, Path]:
    """Return ('scene'|'printed', png path). Live play always shows the room."""
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    if str(getattr(world, 'mode', '') or '') == 'book_dungeon':
        from puca_dungeon.scene_compose import compose_book_dungeon_scene
        path = compose_book_dungeon_scene(world, cache_dir, catalog=catalog, root=root)
        return 'printed', path
    from puca_dungeon.scene_compose import compose_facility_scene
    _spec, path = compose_facility_scene(
        world,
        cache_dir,
        catalog=catalog,
        root=root,
        allow_placeholder=allow_placeholder,
        debug_layers=debug_layers,
    )
    return 'scene', path
