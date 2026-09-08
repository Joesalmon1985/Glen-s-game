"""Developer-only five-face bake-off gallery.

    python -m puca_dungeon.portrait_gallery
"""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


FORBIDDEN_LABEL_WORDS = (
    'iven', 'nessa', 'ruan', 'sarel', 'orderly', 'attendant', 'researcher', 'staff',
)


def main(argv: list[str] | None = None) -> int:
    import argparse
    from tkinter import Tk, ttk

    from PIL import ImageTk

    from puca_dungeon.portrait.bakeoff import STANDARD_POSES, gallery_label
    from puca_dungeon.portrait.manifest import FACE_PROFILE_IDS
    from puca_dungeon.portrait.render import portrait_to_display_rgb, render_portrait

    parser = argparse.ArgumentParser(description='Portrait bake-off gallery')
    parser.add_argument('--thumb', type=int, default=160, help='thumbnail edge in pixels')
    args = parser.parse_args(argv)

    for pid in FACE_PROFILE_IDS:
        label = gallery_label(pid)
        low = label.lower()
        for word in FORBIDDEN_LABEL_WORDS:
            if word in low:
                raise SystemExit(f'Gallery label leaked a character name: {label}')

    root = Tk()
    root.title('Portrait bake-off')
    root.geometry('1680x920')
    outer = ttk.Frame(root, padding=8)
    outer.pack(fill='both', expand=True)
    canvas = ttk.Frame(outer)
    canvas.pack(fill='both', expand=True)

    thumbs: list = []
    scale_edge = max(64, int(args.thumb))
    ttk.Label(canvas, text='FACE 001 – FACE 005  (procedural prototypes)').grid(
        row=0, column=0, columnspan=len(STANDARD_POSES) + 1, sticky='w', pady=(0, 8),
    )
    ttk.Label(canvas, text='').grid(row=1, column=0)
    for col, (name, _pose) in enumerate(STANDARD_POSES, start=1):
        ttk.Label(canvas, text=name).grid(row=1, column=col, padx=2)

    for row, pid in enumerate(FACE_PROFILE_IDS, start=2):
        ttk.Label(canvas, text=gallery_label(pid)).grid(row=row, column=0, sticky='e', padx=(0, 8))
        for col, (_name, pose) in enumerate(STANDARD_POSES, start=1):
            rgb = portrait_to_display_rgb(render_portrait(pid, pose))
            rgb = rgb.resize((scale_edge, scale_edge), resample=__import__('PIL').Image.Resampling.NEAREST)
            photo = ImageTk.PhotoImage(rgb)
            thumbs.append(photo)
            ttk.Label(canvas, image=photo).grid(row=row, column=col, padx=2, pady=2)

    root.mainloop()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
