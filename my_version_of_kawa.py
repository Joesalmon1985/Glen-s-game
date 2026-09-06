"""Puca: local interactive fiction. Run launch.bat, or python my_version_of_kawa.py --text-only.
The original EXE is not rebuilt by these source changes.
"""
import argparse
import copy
import json
import logging
import os
from pathlib import Path
import queue
import sys
import threading
import time
import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox

from puca_core import StoryState, MAX_TURNS, save_state, load_state
from puca_services import Narrator
from puca_images import ImageGenerator
from puca_debug import TurnDebug, scene_as_dict, image_payload, write_last_turn

BG = '#171c22'
PANEL = '#222a33'
FG = '#f0ece2'
MUTED = '#b0b9bd'
ACCENT = '#dbc18b'


def enable_native_pixels():
    """Keep a 2560x1440 window at physical pixels, not Windows DPI-scaled pixels."""
    if sys.platform == 'win32':
        import ctypes
        try:
            ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
        except (AttributeError, OSError):
            ctypes.windll.user32.SetProcessDPIAware()


def resource_path(name):
    return Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parent)) / name


class Voice:
    """One COM-owning worker, with cancellation and no Tk calls."""
    def __init__(self, messages):
        self.queue = queue.Queue()
        self.enabled = threading.Event()
        self.closed = threading.Event()
        self.messages = messages
        self.thread = None

    def speak(self, text):
        if not self.enabled.is_set():
            return
        if self.thread is None or not self.thread.is_alive():
            self.thread = threading.Thread(target=self._run, daemon=True)
            self.thread.start()
        self.queue.put(text)

    def _run(self):
        try:
            import pythoncom
            import win32com.client
            pythoncom.CoInitialize()
            try:
                speaker = win32com.client.Dispatch('SAPI.SpVoice')
                speaker.Rate = 1
                while not self.closed.is_set():
                    try:
                        text = self.queue.get(timeout=0.1)
                    except queue.Empty:
                        continue
                    if not self.enabled.is_set():
                        continue
                    speaker.Speak(text, 3)  # asynchronous, purge stale narration
                    while not speaker.WaitUntilDone(100):
                        pythoncom.PumpWaitingMessages()
                        if self.closed.is_set() or not self.enabled.is_set():
                            speaker.Speak('', 3)
                            break
            finally:
                pythoncom.CoUninitialize()
        except Exception:
            logging.exception('Voice unavailable')
            self.messages.put(('notice', 'Voice is unavailable. You can continue reading.'))

    def mute(self):
        self.enabled.clear()
        while True:
            try:
                self.queue.get_nowait()
            except queue.Empty:
                break


class PucaApp:
    def __init__(self, master, data_dir=None, text_only=False, narrator=None, images=None, debug=False):
        self.master = master
        self.data_dir = Path(data_dir or os.environ.get('PUCA_DATA_DIR') or (Path(os.environ.get('LOCALAPPDATA', Path.home())) / 'Puca'))
        self.cache_dir = self.data_dir / 'images'
        self.save_path = self.data_dir / 'adventure.json'
        self.debug_path = self.data_dir / 'debug-last-turn.json'
        self.narrator = narrator or Narrator(model=os.environ.get('PUCA_MODEL', 'mistral'))
        self.images = images or ImageGenerator(self.cache_dir, resource_path('pixel_style_lora_style_only'))
        self.state = StoryState()
        self.messages = queue.Queue()
        self.voice = Voice(self.messages)
        self.busy = False
        self.closed = False
        self.worker = None
        self.cancel_image = threading.Event()
        self.last_action = ''
        self.action_source = 'typed'
        self.failed_action = None
        self.image_failed = False
        self.pending_scene = None
        self.render_failed = False
        self.save_dirty = False
        self.status_warning = ''
        self.poll_id = None
        self.font_size = 18
        self._pixel_image = None
        self._shown_image_signature = None
        self._start_debug = debug
        self._build(text_only)
        self.master.protocol('WM_DELETE_WINDOW', self.close)
        self.poll_id = self.master.after(40, self._poll)

    def _build(self, text_only):
        self.master.title('Puca - A Dark Fantasy Tale')
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
        outer = ttk.Frame(self.master, padding=28)
        outer.pack(fill='both', expand=True)
        self._outer = outer
        outer.columnconfigure(0, weight=1)
        outer.rowconfigure(3, weight=3)
        outer.rowconfigure(8, weight=1)
        header = ttk.Frame(outer)
        header.grid(row=0, column=0, sticky='ew')
        ttk.Label(header, text='PUCA', font=('Georgia', 36, 'bold'), foreground=ACCENT).pack(side='left')
        ttk.Label(header, text='A small journey into the strange', foreground=MUTED).pack(side='left', padx=16)
        self.score = ttk.Label(header, text='Spirit 100/100  |  10 choices')
        self.score.pack(side='right')

        self.setup = ttk.Frame(outer)
        self.setup.grid(row=1, column=0, sticky='ew', pady=(18, 8))
        ttk.Label(self.setup, text='Your name').pack(side='left')
        self.name_var = tk.StringVar()
        self.name_entry = ttk.Entry(self.setup, textvariable=self.name_var, width=18)
        self.name_entry.pack(side='left', padx=(8, 16))
        ttk.Label(self.setup, text='Where are you?').pack(side='left')
        self.origin_var = tk.StringVar(value='At home')
        self.origin_entry = ttk.Entry(self.setup, textvariable=self.origin_var, width=27)
        self.origin_entry.pack(side='left', padx=8)
        self.play_button = ttk.Button(self.setup, text='Begin', command=self.begin)
        self.play_button.pack(side='left', padx=4)
        self.resume_button = ttk.Button(self.setup, text='Resume', command=self.resume)
        self.resume_button.pack(side='left', padx=4)

        tools = ttk.Frame(outer)
        tools.grid(row=2, column=0, sticky='ew', pady=(5, 12))
        self.images_var = tk.BooleanVar(value=not text_only)
        self.lora_var = tk.BooleanVar(value=True)
        self.voice_var = tk.BooleanVar(value=False)
        self.debug_var = tk.BooleanVar(value=self._start_debug)
        self.image_toggle = ttk.Checkbutton(tools, text='Illustrations', variable=self.images_var)
        self.image_toggle.pack(side='left')
        self.lora_toggle = ttk.Checkbutton(tools, text='Pixel adapter', variable=self.lora_var)
        self.lora_toggle.pack(side='left', padx=10)
        ttk.Checkbutton(tools, text='Read aloud', variable=self.voice_var, command=self.toggle_voice).pack(side='left', padx=10)
        ttk.Checkbutton(tools, text='Debug', variable=self.debug_var, command=self._toggle_debug).pack(side='left', padx=10)
        ttk.Button(tools, text='A-', width=3, command=lambda: self.font(-1)).pack(side='right')
        ttk.Button(tools, text='A+', width=3, command=lambda: self.font(1)).pack(side='right', padx=5)
        self.new_button = ttk.Button(tools, text='New adventure', command=self.new_adventure)
        self.new_button.pack(side='right', padx=10)

        content = ttk.Frame(outer)
        content.grid(row=3, column=0, sticky='nsew')
        content.columnconfigure(1, weight=1)
        content.rowconfigure(0, weight=1)
        self.art_panel = tk.Frame(content, bg=PANEL, width=824)
        self.art_panel.grid(row=0, column=0, sticky='nsew', padx=(0, 18))
        self.art_panel.grid_propagate(False)
        self.art_panel.pack_propagate(False)
        self.image_label = tk.Label(self.art_panel, text='The world will unfold here.\n\nIllustrations are optional.\nThe story never needs to wait\nfor a picture to be displayed.',
                                    bg=PANEL, fg=MUTED, font=('Georgia', 16), wraplength=760)
        self.image_label.pack(fill='both', expand=True, padx=10, pady=10)
        self.story = scrolledtext.ScrolledText(content, wrap='word', width=50, height=18,
                    font=('Georgia', self.font_size), bg=PANEL, fg=FG, insertbackground=FG,
                    relief='flat', padx=18, pady=16, spacing3=12, state='disabled')
        self.story.grid(row=0, column=1, sticky='nsew')
        self._append('Welcome to Puca.\n\nChoose a name and a starting place. Your adventure lasts up to ten choices.\n\nHelpful outcomes restore spirit, harmful outcomes cost spirit, and quiet observation is neutral. The opening never costs spirit.\n\nOllama supplies the story locally. If illustrations are unavailable, turn them off and keep reading.')
        self.choice_frame = ttk.Frame(outer)
        self.choice_frame.grid(row=4, column=0, sticky='ew', pady=(12, 6))
        self.choice_buttons = []
        entry = ttk.Frame(outer)
        entry.grid(row=5, column=0, sticky='ew')
        self.action_var = tk.StringVar()
        self.action_entry = ttk.Entry(entry, textvariable=self.action_var, font=('Segoe UI', 16))
        self.action_entry.pack(side='left', fill='x', expand=True)
        self.action_entry.bind('<Return>', self.submit)
        self.submit_button = ttk.Button(entry, text='Choose', command=self.submit)
        self.submit_button.pack(side='left', padx=(8, 0))
        footer = ttk.Frame(outer)
        footer.grid(row=6, column=0, sticky='ew', pady=(10, 0))
        self.status_var = tk.StringVar(value='Ready. Progress is saved automatically after each choice.')
        ttk.Label(footer, textvariable=self.status_var, foreground=MUTED, wraplength=1600).pack(side='left', fill='x', expand=True)
        self.retry_button = ttk.Button(footer, text='Retry', command=self.retry)
        self.retry_button.pack(side='right')
        self.skip_button = ttk.Button(footer, text='Skip image', command=self.skip_image)
        self.skip_button.pack(side='right', padx=5)
        self.progress = ttk.Progressbar(outer, mode='indeterminate')
        self.progress.grid(row=7, column=0, sticky='ew', pady=(8, 0))
        self.debug_frame = ttk.Frame(outer)
        ttk.Label(self.debug_frame, text='Turn debug', foreground=ACCENT).pack(anchor='w')
        self.debug_text = scrolledtext.ScrolledText(self.debug_frame, wrap='word', height=12,
                    font=('Consolas', 11), bg='#12161b', fg=FG, insertbackground=FG,
                    relief='flat', padx=12, pady=10, state='disabled')
        self.debug_text.pack(fill='both', expand=True, pady=(4, 0))
        self._set_debug_text('Debug mode is on. After each command this panel shows narrator input, interpretation, options, engine apply, and image payload.')
        self.master.bind('<Configure>', self._resize_layout, add='+')
        self.art_panel.bind('<Configure>', self._paint_image, add='+')
        self._toggle_debug()
        self._controls()

    def _resize_layout(self, event):
        if event.widget is not self.master:
            return
        width = min(824, max(220, int(event.width * 0.33)))
        self.art_panel.configure(width=width)
        self.image_label.configure(wraplength=width - 32)

    def _paint_image(self, event=None):
        if self._pixel_image is None:
            return
        from PIL import Image, ImageTk
        available = min(self.art_panel.winfo_width() - 40, self.art_panel.winfo_height() - 40, 768)
        side = max(128, (available // 128) * 128)
        signature = (id(self._pixel_image), side)
        if signature == self._shown_image_signature:
            return
        image = self._pixel_image.resize((side, side), Image.Resampling.NEAREST)
        photo = ImageTk.PhotoImage(image, master=self.master)
        self.image_label.configure(image=photo, text='')
        self.image_label.image = photo
        self._shown_image_signature = signature

    def _append(self, text):
        self.story.configure(state='normal')
        self.story.insert('end', text + '\n\n')
        self.story.configure(state='disabled')
        self.story.see('end')

    def _controls(self):
        def set_state(widget, enabled):
            widget.configure(state='normal' if enabled else 'disabled')
        active = self.state.arrived and not self.state.finished and not self.busy
        set_state(self.submit_button, active)
        set_state(self.action_entry, active)
        for button in self.choice_buttons:
            set_state(button, active)
        for widget in [self.play_button, self.resume_button, self.new_button, self.name_entry, self.origin_entry, self.image_toggle, self.lora_toggle]:
            set_state(widget, not self.busy)
        set_state(self.retry_button, not self.busy and bool(self.failed_action or self.image_failed or self.pending_scene or self.render_failed or self.save_dirty))
        set_state(self.skip_button, self.busy and self.images_var.get())
        self.score.configure(text=f'Spirit {self.state.spirit}/100  |  Choice {self.state.turn}/{MAX_TURNS}')

    def begin(self):
        if self.busy or self.state.arrived:
            return
        name, origin = self.name_var.get().strip(), self.origin_var.get().strip()
        if not name or not origin or len(name) > 80 or len(origin) > 240:
            self.status_var.set('Enter a name (up to 80 characters) and starting place (up to 240).')
            return
        if self.save_path.exists() and not messagebox.askyesno('Begin a new adventure?', 'This will replace your saved adventure after the opening succeeds. Resume instead to keep playing it.', parent=self.master):
            return
        self.state = StoryState(name=name, origin=origin)
        self.action_source = 'opening'
        self._launch('(The adventure begins)')

    def submit(self, event=None):
        if self.busy or not self.state.arrived or self.state.finished:
            return 'break'
        action = self.action_var.get().strip()
        if not action or len(action) > 800:
            self.status_var.set('Choose an action, up to 800 characters.')
            return 'break'
        if self.action_source != 'choice_button':
            self.action_source = 'typed'
        self._launch(action)
        return 'break'

    def choose(self, action):
        if not self.busy:
            self.action_source = 'choice_button'
            self.action_var.set(action)
            self.submit()

    def _launch(self, action, image_only=False):
        if self.busy or self.closed:
            return
        if self.pending_scene:
            self.status_var.set('Save the pending scene with Retry before choosing another action.')
            return
        self.busy = True  # synchronous guard, BEFORE the worker can start
        self.failed_action = None
        self.image_failed = False
        self.status_warning = ''
        self.last_action = action
        action_source = self.action_source
        self.action_source = 'typed'
        options_at_submit = [button.cget('text') for button in self.choice_buttons]
        self.cancel_image = threading.Event()
        self.progress.configure(mode='indeterminate')
        self.progress.start(12)
        self.status_var.set('Painting the scene...' if image_only else 'Listening for the next part of the story...')
        self._controls()
        snapshot = copy.deepcopy(self.state)
        image_enabled = self.images_var.get()
        use_lora = self.lora_var.get()
        cancel = self.cancel_image
        self.worker = threading.Thread(
            target=self._work,
            args=(snapshot, action, image_enabled, use_lora, cancel, image_only, action_source, options_at_submit),
            daemon=True)
        self.worker.start()

    def _need_image_reasons(self, snapshot, location, scene, prompt=None):
        reasons = []
        if not snapshot.image_key:
            reasons.append('no_cached_image_key')
        elif location.casefold() != snapshot.location.casefold():
            reasons.append('location_changed')
        if scene is not None and scene.visual_changed:
            reasons.append('visual_changed')
        if snapshot.image_key and not ImageGenerator.valid_image(self.cache_dir / (snapshot.image_key + '.png')):
            reasons.append('cached_image_missing_or_invalid')
        # Regenerate when the illustration payload would hash differently (new
        # image_prompt, location, or adapter), even if the LLM left visual_changed false.
        if prompt is not None and snapshot.image_key:
            try:
                new_key = self.images.key(location, prompt)
            except Exception:
                new_key = ''
            if new_key and new_key != snapshot.image_key:
                reasons.append('illustration_content_changed')
        return reasons

    def _work(self, snapshot, action, image_enabled, use_lora, cancel, image_only, action_source='typed', options_at_submit=None):
        start = time.monotonic()
        committed = False
        turn = TurnDebug(player_command=action, action_source=action_source,
                         options_available_at_submit=list(options_at_submit or []))
        try:
            # The previous illustration has released its live CUDA tensors before the next Ollama request.
            try:
                self.images.release_gpu()
            except Exception:
                logging.exception('Image cleanup failed; narration remains available')
                self.images.pipe = None
                image_enabled = False
                self.messages.put(('notice', 'Image cleanup failed. Continuing with text; restart before enabling illustrations again.'))
            scene = None
            if image_only:
                last = snapshot.history[-1]
                location, prompt = last['location'], last['image_prompt']
                need_image = True
                reasons = ['image_only_retry']
            else:
                scene = self.narrator.ask(snapshot, action)
                turn.sent_to_narrator = getattr(self.narrator, 'last_request', None) or {}
                turn.interpretation = scene_as_dict(scene)
                if self.closed:
                    return
                receipt = {'ready': threading.Event(), 'accepted': False, 'turn_debug': turn}
                self.messages.put(('scene', action, scene, not snapshot.arrived, receipt))
                while not receipt['ready'].wait(0.05):
                    if self.closed:
                        return
                if not receipt['accepted']:
                    return
                committed = True
                location, prompt = scene.location, scene.image_prompt
                if self.images.use_lora != use_lora:
                    self.images.release_gpu()
                    self.images.pipe = None
                    self.images.adapter_loaded = False
                    self.images._adapter_hash = None
                    self.images.use_lora = use_lora
                reasons = self._need_image_reasons(snapshot, location, scene, prompt)
                need_image = bool(reasons)
            cache_key = ''
            cache_hit = False
            generated = False
            try:
                cache_key = self.images.key(location, prompt)
                cache_hit = ImageGenerator.valid_image(self.cache_dir / (cache_key + '.png'))
            except Exception:
                cache_key = ''
            turn.sent_to_image_generation = image_payload(
                location, prompt, use_lora=use_lora, need_image=need_image, reasons=reasons,
                images_enabled=image_enabled, cancelled=cancel.is_set(), cache_key=cache_key,
                cache_hit=cache_hit and need_image)
            self.messages.put(('debug', turn))
            if image_enabled and need_image and not cancel.is_set():
                self.messages.put(('status', 'The story is ready to read. Painting its illustration...'))
                if self.images.use_lora != use_lora:
                    self.images.release_gpu()
                    self.images.pipe = None
                    self.images.adapter_loaded = False
                    self.images._adapter_hash = None
                    self.images.use_lora = use_lora
                key, path = self.images.generate(location, prompt, cancel=cancel,
                    progress=lambda step, total: self.messages.put(('progress', step, total)))
                generated = True
                turn.sent_to_image_generation = image_payload(
                    location, prompt, use_lora=use_lora, need_image=need_image, reasons=reasons,
                    images_enabled=True, cache_key=key, cache_hit=False, generated=generated)
                self.messages.put(('debug', turn))
                if not self.closed:
                    self.messages.put(('image', key, str(path)))
        except Exception as exc:
            logging.exception('Puca generation failed')
            if not self.closed:
                self.messages.put(('image_error' if committed or image_only else 'error', str(exc)))
        finally:
            self.messages.put(('done', round(time.monotonic() - start, 2)))

    def _poll(self):
        if self.closed:
            return
        try:
            while True:
                event = self.messages.get_nowait()
                try:
                    self._handle(event)
                except Exception:
                    logging.exception('UI event failed')
                    self.status_warning = 'A display or save operation failed. Your existing save was not intentionally replaced.'
                    self.status_var.set(self.status_warning)
        except queue.Empty:
            pass
        self.poll_id = self.master.after(40, self._poll)

    def _handle(self, event):
        kind = event[0]
        if kind == 'scene':
            action, scene, opening = event[1:4]
            receipt = event[4] if len(event) > 4 else None
            candidate = copy.deepcopy(self.state)
            self.pending_scene = (action, scene, opening)
            facts_before = list(candidate.facts)
            try:
                delta = candidate.apply(action, scene, opening=opening)
                save_state(self.save_path, candidate)
            except (OSError, ValueError) as exc:
                self.status_warning = f'Could not save this scene: {exc}. Free space or fix the folder, then Retry. Your turn was not spent.'[:500]
                self.status_var.set(self.status_warning)
                if receipt:
                    receipt['ready'].set()
                self._controls()
                return
            self.state = candidate
            self.pending_scene = None
            self.save_dirty = False
            if receipt:
                turn = receipt.get('turn_debug')
                if turn is not None:
                    turn.sent_to_game_engine = {
                        'action': action,
                        'opening': opening,
                        'spirit_classification': scene.spirit,
                        'spirit_delta': delta,
                        'spirit_before': candidate.spirit - delta,
                        'spirit_after': candidate.spirit,
                        'turn_after': candidate.turn,
                        'location_after': candidate.location,
                        'facts_added': [f for f in candidate.facts if f not in facts_before],
                        'finished': candidate.finished,
                        'history_entries': len(candidate.history),
                    }
                    self._publish_debug(turn)
                receipt['accepted'] = True
                receipt['ready'].set()
            # Persistence is complete before any rendering operation can fail.
            self.render_failed = True
            self.action_var.set('')
            if opening:
                self.story.configure(state='normal')
                self.story.delete('1.0', 'end')
                self.story.configure(state='disabled')
            self._append(('Arrival' if opening else f'Choice {self.state.turn}: {action}') + '\n\n' + scene.narration)
            if not opening:
                self._append(f'Spirit {delta:+d}  |  {self.state.spirit}/100')
            if self.state.finished:
                self._append('Your spirit has faded. This adventure has ended.' if self.state.spirit <= 0 else 'Your adventure is complete. Your choices remain in the story above.')
            self._choices(scene.choices if not self.state.finished else ())
            self.voice.speak(scene.narration)
            self.render_failed = False
            self._controls()
        elif kind == 'debug':
            self._publish_debug(event[1])
        elif kind == 'image':
            self.state.image_key = event[1]
            self._show_image(Path(event[2]))
            self._autosave()
        elif kind == 'error':
            self.failed_action = self.last_action
            self.status_warning = str(event[1])[:500]
            self.status_var.set(self.status_warning)
        elif kind == 'image_error':
            self.image_failed = True
            self.status_warning = ('Illustration skipped. The story is saved; continue, retry the image, or turn illustrations off. ' + str(event[1]))[:500]
            self.status_var.set(self.status_warning)
        elif kind == 'notice':
            self.status_warning = event[1]
            self.status_var.set(event[1])
        elif kind == 'status':
            self.status_var.set(event[1])
        elif kind == 'progress':
            self.progress.stop()
            self.progress.configure(mode='determinate', maximum=event[2], value=event[1])
        elif kind == 'done':
            self.busy = False
            self.worker = None
            self.progress.stop()
            self.progress.configure(value=0)
            self.status_var.set(self.status_warning or ('Adventure complete. Start a new one whenever you wish.' if self.state.finished else 'Ready for your next choice. Progress saved.'))
            logging.info('Generation job completed in %.2fs', event[1])
            self._controls()
            if self.state.arrived and not self.state.finished:
                self.action_entry.focus_set()

    def _toggle_debug(self):
        if self.debug_var.get():
            self.debug_frame.grid(row=8, column=0, sticky='nsew', pady=(8, 0))
        else:
            self.debug_frame.grid_remove()

    def _set_debug_text(self, text):
        self.debug_text.configure(state='normal')
        self.debug_text.delete('1.0', 'end')
        self.debug_text.insert('1.0', text)
        self.debug_text.configure(state='disabled')
        self.debug_text.see('1.0')

    def _publish_debug(self, turn):
        try:
            write_last_turn(self.debug_path, turn)
        except OSError:
            logging.exception('Could not write debug-last-turn.json')
        if self.debug_var.get():
            self._set_debug_text(turn.format_text())

    def _choices(self, choices):
        for button in self.choice_buttons:
            button.destroy()
        self.choice_buttons = []
        for text in choices:
            button = ttk.Button(self.choice_frame, text=text[:72], command=lambda action=text: self.choose(action))
            button.pack(fill='x', pady=(0, 3))
            self.choice_buttons.append(button)

    def _autosave(self):
        try:
            save_state(self.save_path, self.state)
            self.save_dirty = False
        except (OSError, ValueError) as exc:
            self.save_dirty = True
            logging.exception('Autosave failed')
            self.status_warning = f'The story is still on screen, but could not save: {exc}'[:500]
            self.status_var.set(self.status_warning)

    def _show_image(self, path):
        try:
            from PIL import Image, ImageTk
            with Image.open(path) as source:
                # Keep the pixel-art grid; upscale for display without a larger AI render.
                self._pixel_image = source.convert('RGB').resize((128, 128), Image.Resampling.NEAREST)
            self._shown_image_signature = None
            self._paint_image()
            return True
        except Exception:
            logging.exception('Image display failed')
            self.status_warning = 'The illustration could not be displayed. Your story is still saved.'
            self.status_var.set(self.status_warning)
            self.state.image_key = ''
            self.image_failed = True
            return False

    def retry(self):
        if self.busy:
            return
        if self.pending_scene:
            pending = self.pending_scene
            self.status_warning = ''
            self._handle(('scene', *pending))
            if not self.pending_scene:
                self.status_var.set('Scene saved. Continue your adventure.')
                if self.images_var.get():
                    self.image_failed = True
            self._controls()
        elif self.render_failed:
            self.resume(confirm=False)
            self.render_failed = False
            self._controls()
        elif self.save_dirty:
            self._autosave()
            if not self.save_dirty:
                self.status_var.set('Progress saved.')
            self._controls()
        elif self.failed_action:
            self._launch(self.failed_action)
        elif self.image_failed and self.state.history:
            self.images_var.set(True)
            self._launch('', image_only=True)

    def skip_image(self):
        self.cancel_image.set()
        self.status_var.set('Skipping illustration at the next safe step. Any first-time download may need to finish.')

    def resume(self, confirm=True):
        if self.busy:
            return
        if confirm and (self.pending_scene or self.save_dirty) and not messagebox.askyesno('Discard pending changes?', 'Resume will discard a scene or image reference that could not be saved. Continue?', parent=self.master):
            return
        try:
            restored = load_state(self.save_path)
        except ValueError as exc:
            self.status_var.set(str(exc))
            return
        self.state = restored
        self.name_var.set(restored.name)
        self.origin_var.set(restored.origin)
        self.story.configure(state='normal')
        self.story.delete('1.0', 'end')
        self.story.configure(state='disabled')
        for index, record in enumerate(restored.history):
            self._append(('Arrival' if index == 0 else f'Choice {index}: {record["action"]}') + '\n\n' + record['narration'])
        self._choices(restored.history[-1]['choices'] if restored.history and not restored.finished else ())
        self.failed_action = None
        self.image_failed = False
        self.pending_scene = None
        self.save_dirty = False
        self.render_failed = False
        if restored.image_key:
            path = self.cache_dir / (restored.image_key + '.png')
            if ImageGenerator.valid_image(path):
                self._show_image(path)
            else:
                self.state.image_key = ''
                self.image_failed = True
                self._pixel_image = None
                self.image_label.configure(image='', text='Saved illustration is missing. Retry to paint it again.')
        self.status_var.set('Story restored. Retry to replace the missing illustration.' if self.image_failed else ('Saved adventure restored.' if not restored.finished else 'This saved adventure is complete. Start a new one to play again.'))
        self._controls()

    def new_adventure(self):
        if self.busy:
            return
        if (self.state.arrived or self.pending_scene or self.save_dirty) and not messagebox.askyesno('New adventure?', 'Your current save will be replaced only after the new opening succeeds. Continue?', parent=self.master):
            return
        self.voice.mute()
        self.voice_var.set(False)
        self.state = StoryState()
        self.failed_action = None
        self.image_failed = False
        self.pending_scene = None
        self.render_failed = False
        self.save_dirty = False
        self.action_var.set('')
        self._choices(())
        self.image_label.configure(image='', text='A new world is waiting.')
        self._pixel_image = None
        self._shown_image_signature = None
        self.image_label.image = None
        self.status_var.set('Choose a name and starting place, then Begin.')
        self._controls()

    def toggle_voice(self):
        if self.voice_var.get():
            self.voice.enabled.set()
        else:
            self.voice.mute()

    def font(self, delta):
        self.font_size = max(10, min(28, self.font_size + delta))
        self.story.configure(font=('Georgia', self.font_size))

    def close(self):
        if self.closed:
            return
        self.closed = True
        self.cancel_image.set()
        self.voice.closed.set()
        self.voice.mute()
        if self.poll_id:
            self.master.after_cancel(self.poll_id)
        self.master.destroy()


def main():
    parser = argparse.ArgumentParser(description='Puca local fantasy adventure')
    parser.add_argument('--text-only', action='store_true', help='Start with illustrations disabled; Ollama is still required')
    parser.add_argument('--debug', action='store_true', help='Show turn debug panel (narrator, options, engine, image payload)')
    parser.add_argument('--verify-startup', action='store_true', help='Run a real AI, illustration and save/resume check in an isolated save folder, then close')
    args = parser.parse_args()
    data_dir = Path(os.environ.get('PUCA_DATA_DIR') or (Path(os.environ.get('LOCALAPPDATA', Path.home())) / 'Puca'))
    if args.verify_startup:
        data_dir = data_dir / ('runtime-check-' + str(time.time_ns()))
    try:
        data_dir.mkdir(parents=True, exist_ok=True)
        logging.basicConfig(filename=data_dir / 'puca.log', level=logging.INFO,
                            format='%(asctime)s %(levelname)s %(message)s', encoding='utf-8')
    except OSError:
        logging.basicConfig(level=logging.INFO)
    enable_native_pixels()
    root = tk.Tk()
    app = PucaApp(root, data_dir=data_dir, text_only=args.text_only and not args.verify_startup, debug=args.debug)
    if args.verify_startup:
        from puca_smoke import run
        run(app)
    root.mainloop()
    if args.verify_startup and getattr(app, 'runtime_check_failed', True):
        raise SystemExit(1)

if __name__ == '__main__':
    main()
