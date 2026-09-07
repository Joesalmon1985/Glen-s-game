"""Deathtrap Dungeon Tk GUI — Puca-like layout, no visible sheet metrics, with illustrations."""
from __future__ import annotations

import argparse
import logging
import os
import queue
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, scrolledtext, ttk

# Allow `python -m puca_dungeon.gui` and `python puca_dungeon/gui.py`
_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from puca_dungeon.content_loader import get_passage
from puca_dungeon.interpret import HeuristicInterpreter, InterpreterUnavailable, OllamaInterpreter
from puca_dungeon.narrate import OllamaNarrator, TemplateNarrator
from puca_dungeon.session import GameSession
from puca_images import ImageGenerator

BG = '#171c22'
PANEL = '#222a33'
FG = '#f0ece2'
MUTED = '#b0b9bd'
ACCENT = '#dbc18b'


def enable_native_pixels():
    """Keep a 2560x1440 window at physical pixels, not Windows DPI-scaled pixels."""
    if sys.platform != 'win32':
        return
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            import ctypes
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


def resource_path(name: str) -> Path:
    base = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parents[1]))
    return base / name


class DeathtrapGui:
    def __init__(
        self,
        master,
        data_dir=None,
        text_only=False,
        seed=91,
        model='mistral',
        allow_heuristic_fallback=True,
    ):
        self.master = master
        self.data_dir = Path(
            data_dir
            or os.environ.get('PUCA_DEATHTRAP_DATA')
            or (Path(os.environ.get('LOCALAPPDATA', Path.home())) / 'Puca' / 'deathtrap')
        )
        self.cache_dir = self.data_dir / 'images'
        self.save_path = self.data_dir / 'save.json'
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

        self.seed = seed
        self.model = model
        self.allow_heuristic_fallback = allow_heuristic_fallback
        self.session: GameSession | None = None
        self.messages = queue.Queue()
        self.turn_busy = False
        self.image_busy = False
        self.closed = False
        self.worker = None
        self.image_worker = None
        self.cancel_image = threading.Event()
        self.poll_id = None
        self.font_size = 18
        self._pixel_image = None
        self._shown_image_signature = None
        self.status_warning = ''
        self.example_hint = None
        self.images = ImageGenerator(
            self.cache_dir,
            resource_path('pixel_style_lora_style_only'),
            use_lora=(resource_path('pixel_style_lora_style_only') / 'adapter_model.safetensors').is_file(),
        )

        self._build(text_only)
        self.master.protocol('WM_DELETE_WINDOW', self.close)
        self.poll_id = self.master.after(40, self._poll)

    def _build(self, text_only):
        self.master.title('Puca')
        self.master.tk.call('tk', 'scaling', 96 / 72)
        self.master.geometry('2560x1440')
        self.master.minsize(780, 680)
        self.master.configure(bg=BG)
        style = ttk.Style(self.master)
        style.theme_use('clam')
        style.configure('TFrame', background=BG)
        style.configure('TLabel', background=BG, foreground=FG, font=('Segoe UI', 12))
        style.configure('TButton', font=('Segoe UI', 12), padding=9)
        style.configure('TCheckbutton', background=BG, foreground=FG, font=('Segoe UI', 12))
        style.configure('TEntry', font=('Segoe UI', 12))
        style.configure('TCombobox', font=('Segoe UI', 12))

        outer = ttk.Frame(self.master, padding=28)
        outer.pack(fill='both', expand=True)
        self._outer = outer
        outer.columnconfigure(0, weight=1)
        outer.rowconfigure(3, weight=3)

        header = ttk.Frame(outer)
        header.grid(row=0, column=0, sticky='ew')
        ttk.Label(header, text='PUCA', font=('Georgia', 32, 'bold'), foreground=ACCENT).pack(side='left')
        ttk.Label(header, text='Level 1 — the cell', foreground=MUTED).pack(side='left', padx=16)
        # Intentionally no Skill / Stamina / Luck / spirit meters

        self.setup = ttk.Frame(outer)
        self.setup.grid(row=1, column=0, sticky='ew', pady=(18, 8))
        ttk.Label(self.setup, text='Your name').pack(side='left')
        self.name_var = tk.StringVar(value='Adventurer')
        self.name_entry = ttk.Entry(self.setup, textvariable=self.name_var, width=18)
        self.name_entry.pack(side='left', padx=(8, 16))
        ttk.Label(self.setup, text='Potion').pack(side='left')
        self.potion_var = tk.StringVar(value='potion_skill')
        potion = ttk.Combobox(
            self.setup,
            textvariable=self.potion_var,
            values=('potion_skill', 'potion_strength', 'potion_fortune'),
            width=18,
            state='readonly',
        )
        potion.pack(side='left', padx=8)
        self.play_button = ttk.Button(self.setup, text='Wake up', command=self.begin)
        self.play_button.pack(side='left', padx=4)
        self.resume_button = ttk.Button(self.setup, text='Resume', command=self.resume)
        self.resume_button.pack(side='left', padx=4)

        tools = ttk.Frame(outer)
        tools.grid(row=2, column=0, sticky='ew', pady=(5, 12))
        self.images_var = tk.BooleanVar(value=not text_only)
        self.lora_var = tk.BooleanVar(value=True)
        self.image_toggle = ttk.Checkbutton(tools, text='Illustrations', variable=self.images_var)
        self.image_toggle.pack(side='left')
        self.lora_toggle = ttk.Checkbutton(tools, text='Pixel adapter', variable=self.lora_var)
        self.lora_toggle.pack(side='left', padx=10)
        ttk.Button(tools, text='A-', width=3, command=lambda: self.font(-1)).pack(side='right')
        ttk.Button(tools, text='A+', width=3, command=lambda: self.font(1)).pack(side='right', padx=5)
        self.new_button = ttk.Button(tools, text='New run', command=self.new_run)
        self.new_button.pack(side='right', padx=10)

        content = ttk.Frame(outer)
        content.grid(row=3, column=0, sticky='nsew')
        content.columnconfigure(1, weight=1)
        content.rowconfigure(0, weight=1)
        self.art_panel = tk.Frame(content, bg=PANEL, width=824)
        self.art_panel.grid(row=0, column=0, sticky='nsew', padx=(0, 18))
        self.art_panel.grid_propagate(False)
        self.art_panel.pack_propagate(False)
        self.image_label = tk.Label(
            self.art_panel,
            text='The room will take shape here.\n\nIllustrations are optional.\nType freely — no meters, no menus of numbers.',
            bg=PANEL, fg=MUTED, font=('Georgia', 16), wraplength=760,
        )
        self.image_label.pack(fill='both', expand=True, padx=10, pady=10)
        self.story = scrolledtext.ScrolledText(
            content, wrap='word', width=50, height=18,
            font=('Georgia', self.font_size), bg=PANEL, fg=FG, insertbackground=FG,
            relief='flat', padx=18, pady=16, spacing3=12, state='disabled',
        )
        self.story.grid(row=0, column=1, sticky='nsew')
        self._append(
            'Welcome to Puca.\n\n'
            'Enter your name and wake in the cell.\n\n'
            'Type what you intend in your own words. There are no on-screen Skill, Stamina, or Luck meters — '
            'only what you can see, feel, and try.\n\n'
            'Illustrations stay on unless you turn them off. Ollama interprets your words locally.'
        )

        examples_row = ttk.Frame(outer)
        examples_row.grid(row=4, column=0, sticky='ew', pady=(12, 6))
        self.example_hint = ttk.Label(
            examples_row,
            text='Try something like (fills the box — you still press Act):',
            foreground=MUTED,
        )
        self.example_hint.pack(side='left', padx=(0, 10))
        self.choice_frame = ttk.Frame(examples_row)
        self.choice_frame.pack(side='left', fill='x', expand=True)
        self.choice_buttons = []

        entry = ttk.Frame(outer)
        entry.grid(row=5, column=0, sticky='ew')
        self.action_var = tk.StringVar()
        self.action_entry = ttk.Entry(entry, textvariable=self.action_var, font=('Segoe UI', 16))
        self.action_entry.pack(side='left', fill='x', expand=True)
        self.action_entry.bind('<Return>', self.submit)
        self.submit_button = ttk.Button(entry, text='Act', command=self.submit)
        self.submit_button.pack(side='left', padx=(8, 0))

        footer = ttk.Frame(outer)
        footer.grid(row=6, column=0, sticky='ew', pady=(10, 0))
        self.status_var = tk.StringVar(value='Ready. Progress saves automatically after each action.')
        ttk.Label(footer, textvariable=self.status_var, foreground=MUTED, wraplength=1600).pack(
            side='left', fill='x', expand=True,
        )
        self.skip_button = ttk.Button(footer, text='Skip image', command=self.skip_image)
        self.skip_button.pack(side='right', padx=5)

        self.progress = ttk.Progressbar(outer, mode='indeterminate')
        self.progress.grid(row=7, column=0, sticky='ew', pady=(8, 0))

        self.master.bind('<Configure>', self._resize_layout, add='+')
        self.art_panel.bind('<Configure>', self._paint_image, add='+')
        self._controls(active=False)

    def _append(self, text: str):
        self.story.configure(state='normal')
        if self.story.get('1.0', 'end').strip():
            self.story.insert('end', '\n\n')
        self.story.insert('end', text)
        self.story.see('end')
        self.story.configure(state='disabled')

    def _clear_story(self):
        self.story.configure(state='normal')
        self.story.delete('1.0', 'end')
        self.story.configure(state='disabled')

    def _controls(self, active=None):
        if active is None:
            active = (
                self.session is not None
                and not self.turn_busy
                and self.session.world.sheet.alive
                and not self.session.world.victory
            )

        def set_state(widget, enabled):
            widget.configure(state='normal' if enabled else 'disabled')

        set_state(self.submit_button, active)
        set_state(self.action_entry, active)
        for button in self.choice_buttons:
            set_state(button, active)
        set_state(self.play_button, self.session is None and not self.turn_busy and not self.image_busy)
        set_state(self.resume_button, not self.turn_busy and not self.image_busy)
        set_state(self.new_button, not self.turn_busy and not self.image_busy)
        set_state(self.skip_button, self.image_busy and self.images_var.get())

    def _resize_layout(self, event):
        if event.widget is not self.master:
            return
        width = min(824, max(220, int(event.width * 0.33)))
        self.art_panel.configure(width=width)
        self.image_label.configure(wraplength=width - 32)

    def _paint_image(self, event=None):
        if self._pixel_image is None:
            return
        try:
            from PIL import Image, ImageTk
        except ImportError:
            return
        panel_w = max(1, self.art_panel.winfo_width() - 20)
        panel_h = max(1, self.art_panel.winfo_height() - 20)
        img = self._pixel_image
        if not hasattr(img, 'size'):
            return
        # Keep aspect; ImageTk expects RGB
        fitted = img.copy()
        fitted.thumbnail((panel_w, panel_h), Image.Resampling.NEAREST)
        photo = ImageTk.PhotoImage(fitted)
        self.image_label.configure(image=photo, text='')
        self.image_label.image = photo

    def _show_image(self, path: Path | str | None):
        if not path:
            return
        path = Path(path)
        if not path.is_file():
            self.status_warning = 'Illustration file missing.'
            return
        try:
            from PIL import Image
            with Image.open(path) as raw:
                self._pixel_image = raw.convert('RGB')
            self._shown_image_signature = str(path)
            self._paint_image()
        except Exception as exc:
            self.status_warning = f'Could not display illustration: {exc}'

    def _choice_labels(self) -> list[str]:
        if not self.session:
            return []
        world = self.session.world
        if world.combat.active:
            labels = ['Attack', 'Flee'] if world.combat.flee_to is not None else ['Attack']
            if world.sheet.potion and not world.sheet.potion_used:
                labels.append('Drink potion')
            if world.sheet.provisions > 0:
                labels.append('Eat a provision')
            return labels
        passage = self.session.current_passage()
        choices = passage.get('choices') if isinstance(passage, dict) else getattr(passage, 'choices', None)
        return [
            c.get('label') or c.get('id')
            for c in (choices or [])
            if isinstance(c, dict)
        ]

    def _refresh_choices(self):
        for button in self.choice_buttons:
            button.destroy()
        self.choice_buttons = []
        for label in self._choice_labels():
            btn = ttk.Button(self.choice_frame, text=label, command=lambda t=label: self.fill_example(t))
            btn.pack(side='left', padx=(0, 8), pady=2)
            self.choice_buttons.append(btn)

    def _make_session(self, name: str, potion_id: str) -> GameSession:
        lora_ok = self.lora_var.get() and (
            resource_path('pixel_style_lora_style_only') / 'adapter_model.safetensors'
        ).is_file()
        self.images.use_lora = lora_ok

        interpreter = None
        narrator = None
        try:
            interpreter = OllamaInterpreter(model=self.model)
            if not interpreter.ping():
                raise InterpreterUnavailable('Ollama not ready')
            narrator = OllamaNarrator(model=self.model)
        except Exception:
            if not self.allow_heuristic_fallback:
                raise
            interpreter = HeuristicInterpreter()
            narrator = TemplateNarrator()

        return GameSession(
            player_name=name,
            seed=self.seed,
            potion_id=potion_id,
            interpreter=interpreter,
            debug=False,
            narrator=narrator,
            allow_heuristic_fallback=self.allow_heuristic_fallback,
            ollama_model=self.model,
            generate_images=False,  # GUI drives generation so we can cancel / toggle
            image_generator=self.images,
            image_cache_dir=self.cache_dir,
            start_mode='facility',
        )

    def begin(self):
        if self.turn_busy or self.image_busy:
            return
        name = (self.name_var.get() or 'Adventurer').strip()[:40] or 'Adventurer'
        potion = self.potion_var.get() or 'potion_skill'
        try:
            self.session = self._make_session(name, potion)
        except InterpreterUnavailable as exc:
            messagebox.showerror('Puca', str(exc))
            return
        self._clear_story()
        self._append(self.session.opening_text)
        self._refresh_choices()
        self.status_var.set('You wake in the cell.')
        self._controls(active=True)
        self.action_entry.focus_set()
        if self.images_var.get():
            self._launch_image_only()
        else:
            self._autosave()

    def resume(self):
        if self.turn_busy or self.image_busy:
            return
        if not self.save_path.is_file():
            messagebox.showinfo('Puca', 'No saved run found.')
            return
        name = (self.name_var.get() or 'Adventurer').strip()[:40] or 'Adventurer'
        potion = self.potion_var.get() or 'potion_skill'
        try:
            self.session = self._make_session(name, potion)
            self.session.load(self.save_path)
        except Exception as exc:
            messagebox.showerror('Puca', f'Could not load save: {exc}')
            return
        self._clear_story()
        passage = self.session.current_passage()
        text = passage.get('text') if isinstance(passage, dict) else getattr(passage, 'text', '')
        self._append(text or self.session.opening_text)
        self._refresh_choices()
        self.status_var.set('Saved run restored.')
        alive = self.session.world.sheet.alive and not self.session.world.victory
        if self.session.world.facility and self.session.world.facility.slept:
            alive = False
        self._controls(active=alive)
        if self.images_var.get() and alive:
            self._launch_image_only()

    def new_run(self):
        if self.turn_busy or self.image_busy:
            return
        self.cancel_image.set()
        self.session = None
        self._clear_story()
        self._append(
            'New run ready.\n\nEnter your name and wake in the cell again.'
        )
        for button in self.choice_buttons:
            button.destroy()
        self.choice_buttons = []
        self._pixel_image = None
        self.image_label.configure(
            image='',
            text='The room will take shape here.\n\nIllustrations are optional.',
        )
        self.status_var.set('Ready for a new run.')
        self._controls(active=False)

    def fill_example(self, label: str):
        """Fill the free-text box only — examples are not a choice menu."""
        self.action_var.set(label)
        self.action_entry.focus_set()
        self.action_entry.icursor('end')

    def submit(self, event=None):
        if self.turn_busy or not self.session:
            return
        text = (self.action_var.get() or '').strip()
        if not text:
            return
        if not self.session.world.sheet.alive or self.session.world.victory:
            return
        self.action_var.set('')
        self._launch(text)

    def skip_image(self):
        self.cancel_image.set()
        self.status_var.set('Skipping illustration at the next safe step.')

    def font(self, delta: int):
        self.font_size = max(12, min(28, self.font_size + delta))
        self.story.configure(font=('Georgia', self.font_size))

    def _reset_progress_indeterminate(self):
        self.progress.stop()
        self.progress.configure(mode='indeterminate', value=0)
        self.progress.start(12)

    def _launch(self, action: str):
        # Cancel any in-flight paint when the player acts again
        self.cancel_image.set()
        self.turn_busy = True
        self.cancel_image = threading.Event()
        self._controls(active=False)
        self._reset_progress_indeterminate()
        self.status_var.set('Resolving your action...')
        self.worker = threading.Thread(target=self._work, args=(action,), daemon=True)
        self.worker.start()

    def _launch_image_only(self):
        self.cancel_image.set()
        self.cancel_image = threading.Event()
        self.image_busy = True
        self._controls()
        self._reset_progress_indeterminate()
        self.status_var.set('The story is ready to read. Painting its illustration...')
        self.image_worker = threading.Thread(target=self._work_image_only, daemon=True)
        self.image_worker.start()

    def _work(self, action: str):
        assert self.session is not None
        try:
            self.session.generate_images = False
            trace = self.session.submit(action)
            prose = trace.narrator_output or ''
            self.messages.put(('prose', prose))
            self.messages.put(('choices', self._choice_labels()))

            ended = (
                not self.session.world.sheet.alive
                or self.session.world.victory
                or self.session.world.ending in ('death', 'victory')
            )
            if ended:
                if self.session.world.victory or self.session.world.ending == 'victory':
                    self.messages.put(('ended', 'victory'))
                else:
                    self.messages.put(('ended', 'death'))

            self._autosave()
            # Unlock input before paint — story advances first
            self.messages.put(('turn_done', None))

            if self.images_var.get() and not ended and not self.cancel_image.is_set():
                self.messages.put(('status', 'Ready — painting the scene...'))
                self.messages.put(('image_busy', True))
                self._generate_current_image(trace)
            self.messages.put(('image_done', None))
        except Exception as exc:
            logging.exception('Deathtrap turn failed')
            self.messages.put(('error', str(exc)))

    def _work_image_only(self):
        assert self.session is not None
        try:
            from puca_dungeon.image_prompt import build_image_prompt

            prompt = build_image_prompt(self.session.world, self.session.current_passage())
            if self.cancel_image.is_set():
                self.messages.put(('image_done', None))
                return
            self.images.use_lora = self.lora_var.get() and (
                resource_path('pixel_style_lora_style_only') / 'adapter_model.safetensors'
            ).is_file()
            _key, path = self.images.generate(
                f'passage_{self.session.world.passage_id}',
                prompt,
                cancel=self.cancel_image,
                progress=lambda step, total: self.messages.put(('progress', step, total)),
            )
            self.session.last_image_path = Path(path)
            self.session.world.last_image_prompt = prompt
            self.messages.put(('image', str(path)))
            self._autosave()
            self.messages.put(('image_done', None))
        except Exception as exc:
            logging.exception('Deathtrap image failed')
            self.messages.put(('notice', f'Illustration failed: {exc}'))
            self.messages.put(('image_done', None))

    def _generate_current_image(self, trace):
        assert self.session is not None
        prompt = (trace.image or {}).get('full_prompt') or ''
        if not prompt:
            from puca_dungeon.image_prompt import build_image_prompt
            prompt = build_image_prompt(self.session.world, self.session.current_passage())
        decision = (trace.image or {}).get('decision')
        if decision == 'REUSE' and self.session.last_image_path and Path(self.session.last_image_path).is_file():
            self.messages.put(('image', str(self.session.last_image_path)))
            return
        if self.cancel_image.is_set():
            return
        self.images.use_lora = self.lora_var.get() and (
            resource_path('pixel_style_lora_style_only') / 'adapter_model.safetensors'
        ).is_file()
        try:
            _key, path = self.images.generate(
                f'passage_{self.session.world.passage_id}',
                prompt,
                cancel=self.cancel_image,
                progress=lambda step, total: self.messages.put(('progress', step, total)),
            )
            self.session.last_image_path = Path(path)
            self.messages.put(('image', str(path)))
        except RuntimeError as exc:
            if 'cancelled' in str(exc).lower():
                return
            raise

    def _autosave(self):
        if not self.session:
            return
        try:
            self.session.save(self.save_path)
        except Exception:
            logging.exception('autosave failed')

    def _poll(self):
        if self.closed:
            return
        try:
            while True:
                event = self.messages.get_nowait()
                self._handle(event)
        except queue.Empty:
            pass
        self.poll_id = self.master.after(40, self._poll)

    def _alive(self) -> bool:
        return (
            self.session is not None
            and self.session.world.sheet.alive
            and not self.session.world.victory
            and self.session.world.ending not in ('death', 'victory')
        )

    def _handle(self, event):
        kind = event[0]
        if kind == 'prose':
            self._append(event[1])
        elif kind == 'choices':
            for button in self.choice_buttons:
                button.destroy()
            self.choice_buttons = []
            for label in event[1]:
                btn = ttk.Button(self.choice_frame, text=label, command=lambda t=label: self.fill_example(t))
                btn.pack(side='left', padx=(0, 8), pady=2)
                self.choice_buttons.append(btn)
        elif kind == 'image':
            self._show_image(event[1])
        elif kind == 'progress':
            self.progress.stop()
            self.progress.configure(mode='determinate', maximum=event[2], value=event[1])
        elif kind == 'status':
            self.status_var.set(event[1])
        elif kind == 'notice':
            self.status_var.set(event[1])
            self.status_warning = event[1]
        elif kind == 'image_busy':
            self.image_busy = True
            self._controls()
        elif kind == 'turn_done':
            self.progress.stop()
            self.progress.configure(mode='indeterminate', value=0)
            self.turn_busy = False
            alive = self._alive()
            self._controls(active=alive)
            if alive and not self.images_var.get():
                self.status_var.set(self.status_warning or 'Ready for your next action.')
                self.status_warning = ''
            elif alive:
                self.status_var.set(self.status_warning or 'Ready — painting the scene...')
        elif kind == 'image_done':
            self.progress.stop()
            self.progress.configure(mode='indeterminate', value=0)
            self.image_busy = False
            alive = self._alive()
            self._controls(active=alive and not self.turn_busy)
            if alive and not self.turn_busy:
                self.status_var.set(self.status_warning or 'Ready for your next action.')
                self.status_warning = ''
        elif kind == 'error':
            self.progress.stop()
            self.progress.configure(mode='indeterminate', value=0)
            self.turn_busy = False
            self.image_busy = False
            messagebox.showerror('Puca', event[1])
            self._controls(active=self.session is not None and self._alive())
        elif kind == 'ended':
            if event[1] == 'victory':
                self.status_var.set('Victory.')
                self._append('[You emerge victorious.]')
            else:
                self.status_var.set('Your adventure ends here.')
                self._append('[You have died.]')
        elif kind == 'done':
            # Legacy compatibility — treat as full unlock
            self.progress.stop()
            self.turn_busy = False
            self.image_busy = False
            self._controls(active=self._alive())

    def close(self):
        if self.closed:
            return
        self.closed = True
        self.cancel_image.set()
        if self.poll_id:
            self.master.after_cancel(self.poll_id)
        self.master.destroy()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description='Deathtrap Dungeon — graphical play')
    parser.add_argument('--text-only', action='store_true', help='Start with illustrations off')
    parser.add_argument('--seed', type=int, default=91)
    parser.add_argument('--model', default=os.environ.get('PUCA_MODEL', 'mistral'))
    parser.add_argument('--require-ollama', action='store_true', help='Fail if Ollama is down (no heuristic fallback)')
    args = parser.parse_args(argv)

    data_dir = Path(
        os.environ.get('PUCA_DEATHTRAP_DATA')
        or (Path(os.environ.get('LOCALAPPDATA', Path.home())) / 'Puca' / 'deathtrap')
    )
    try:
        data_dir.mkdir(parents=True, exist_ok=True)
        logging.basicConfig(
            filename=data_dir / 'deathtrap-gui.log',
            level=logging.INFO,
            format='%(asctime)s %(levelname)s %(message)s',
            encoding='utf-8',
        )
    except OSError:
        logging.basicConfig(level=logging.INFO)

    enable_native_pixels()
    root = tk.Tk()
    DeathtrapGui(
        root,
        data_dir=data_dir,
        text_only=args.text_only,
        seed=args.seed,
        model=args.model,
        allow_heuristic_fallback=not args.require_ollama,
    )
    root.mainloop()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
