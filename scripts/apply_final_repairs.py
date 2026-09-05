"""Bounded final repairs. Exact replacements are checked before writes.
File tools on this Windows host can report false 'not found' and time out after writing.
This script reads the actual native paths, applies asserted edits, and compiles every module.
"""
from pathlib import Path
root = Path(__file__).resolve().parents[1]

def edit(name, replacements):
    path = root / name
    text = path.read_text(encoding='utf-8')
    for old, new in replacements:
        if new in text:
            continue
        count = text.count(old)
        initial_fields = name == 'my_version_of_kawa.py' and old.startswith('        self.failed_action = None') and count == 2
        assert count == 1 or initial_fields, (name, old[:100], count)
        text = text.replace(old, new, 1)
    compile(text, str(path), 'exec')
    path.write_text(text, encoding='utf-8')
    print('Updated', name)

edit('puca_core.py', [
("    facts: tuple = ()", "    facts: tuple = ()\n    visual_changed: bool = False"),
("        return StoryState(**raw)", """        if records:
            if records[0]['spirit_delta'] != 0:
                raise ValueError('Opening cannot change spirit')
            score = 100
            for record in records:
                score += record['spirit_delta']
                if not 0 <= score <= 100:
                    raise ValueError('Invalid score progression')
            if score != raw['spirit'] or records[-1]['location'] != raw['location']:
                raise ValueError('Saved score/location contradict the history')
        elif raw['spirit'] != 100 or raw['location'] or raw['facts'] or raw['image_key']:
            raise ValueError('Unstarted adventure has inconsistent state')
        return StoryState(**raw)"""),
])

edit('puca_services.py', [
("import json\n", "import json\nimport copy\n"),
("SCHEMA['properties'].update({'spirit'", "SCHEMA['properties']['visual_changed'] = {'type': 'boolean'}\nSCHEMA['required'].append('visual_changed')\nSCHEMA['properties'].update({'spirit'"),
("location is a short STABLE place identifier, unchanged during conversation at the same place.", "location is a short STABLE place identifier, unchanged during conversation at the same place.\nvisual_changed is true ONLY for a major visible reveal, transformation, or new important character, not ordinary dialogue."),
("    return Scene(spirit=spirit, **cleaned)", "    visual_changed = payload.get('visual_changed', False)\n    if type(visual_changed) is not bool:\n        raise GenerationError('Invalid visual change flag. Retry this turn.')\n    return Scene(spirit=spirit, visual_changed=visual_changed, **cleaned)"),
("        body = {'model': self.model, 'system': RULES, 'prompt': json.dumps(context, ensure_ascii=False),", """        # Preserve full history/facts in the save, send bounded excerpts to the AI.
        # UTF-8 byte count conservatively bounds tokens, reserving output and template overhead.
        context = copy.deepcopy(context)
        for entry in context['recent_turns']:
            if 'narration' in entry:
                entry['narration'] = entry['narration'][:500]
        input_budget = 8192 - 900 - 256 - len(RULES.encode('utf-8'))
        encode = lambda: json.dumps(context, ensure_ascii=False)
        omitted = 0
        while len(encode().encode('utf-8')) > input_budget:
            if len(context['recent_turns']) > 1:
                context['recent_turns'].pop(0)
            elif len(context['established_facts']) > 2:
                # Keep the opening goal and latest earned facts; never alter the canonical save.
                context['established_facts'].pop(1)
                omitted += 1
                context['older_facts_omitted'] = omitted
            elif context['recent_turns']:
                context['recent_turns'].pop(0)
            else:
                raise GenerationError('This action is too long for the narrator context. Please shorten it.')
        body = {'model': self.model, 'system': RULES, 'prompt': encode(),"""),
("'num_predict': 650, 'num_ctx': 4096", "'num_predict': 900, 'num_ctx': 8192"),
])

edit('puca_images.py', [
("    def key(self, location, prompt):", """    @staticmethod
    def valid_image(path):
        try:
            from PIL import Image
            with Image.open(path) as image:
                if image.format != 'PNG' or image.size != (512, 512):
                    return False
                image.verify()
            return True
        except (OSError, ValueError, ImportError):
            return False

    def key(self, location, prompt):"""),
("        if self._adapter_hash is None:\n            weights = self.lora_folder / 'adapter_model.safetensors'\n            self._adapter_hash = hashlib.sha256(weights.read_bytes()).hexdigest() if self.use_lora and weights.exists() else 'base'", """        weights = self.lora_folder / 'adapter_model.safetensors'
        config_file = self.lora_folder / 'adapter_config.json'
        if self.use_lora and (not weights.is_file() or not config_file.is_file()):
            raise RuntimeError('Pixel adapter files are missing. Disable the pixel adapter to use base art.')
        if self._adapter_hash is None:
            self._adapter_hash = hashlib.sha256(weights.read_bytes() + config_file.read_bytes()).hexdigest() if self.use_lora else 'base'"""),
("        if destination.is_file():\n            return key, destination", "        if destination.is_file():\n            if self.valid_image(destination):\n                return key, destination\n            destination.unlink()"),
("        self.cache_dir.mkdir(parents=True, exist_ok=True)\n        def callback", "        if cancel and cancel.is_set():\n            self.release_gpu()\n            raise RuntimeError('Illustration cancelled')\n        self.cache_dir.mkdir(parents=True, exist_ok=True)\n        def callback"),
])

edit('my_version_of_kawa.py', [
("        if self.thread is None:\n", "        if self.thread is None or not self.thread.is_alive():\n"),
("        self.failed_action = None\n        self.image_failed = False\n        self.status_warning = ''", "        self.failed_action = None\n        self.image_failed = False\n        self.pending_scene = None\n        self.render_failed = False\n        self.save_dirty = False\n        self.status_warning = ''"),
("not self.busy and bool(self.failed_action or self.image_failed)", "not self.busy and bool(self.failed_action or self.image_failed or self.pending_scene or self.render_failed or self.save_dirty)"),
("        if self.busy or self.closed:\n            return\n        self.busy = True", "        if self.busy or self.closed:\n            return\n        if self.pending_scene:\n            self.status_var.set('Save the pending scene with Retry before choosing another action.')\n            return\n        self.busy = True"),
("            self.images.release_gpu()\n            if image_only:", """            try:
                self.images.release_gpu()
            except Exception:
                logging.exception('Image cleanup failed; narration remains available')
                self.images.pipe = None
                image_enabled = False
                self.messages.put(('notice', 'Image cleanup failed. Continuing with text; restart before enabling illustrations again.'))
            if image_only:"""),
("                self.messages.put(('scene', action, scene, not snapshot.arrived))\n                committed = True", """                receipt = {'ready': threading.Event(), 'accepted': False}
                self.messages.put(('scene', action, scene, not snapshot.arrived, receipt))
                while not receipt['ready'].wait(0.05):
                    if self.closed:
                        return
                if not receipt['accepted']:
                    return
                committed = True"""),
("                need_image = not snapshot.image_key or location.casefold() != snapshot.location.casefold()", "                need_image = (not snapshot.image_key or location.casefold() != snapshot.location.casefold() or scene.visual_changed\n                              or not ImageGenerator.valid_image(self.cache_dir / (snapshot.image_key + '.png')))"),
("            _, action, scene, opening = event\n            delta = self.state.apply(action, scene, opening=opening)", """            action, scene, opening = event[1:4]
            receipt = event[4] if len(event) > 4 else None
            candidate = copy.deepcopy(self.state)
            self.pending_scene = (action, scene, opening)
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
                receipt['accepted'] = True
                receipt['ready'].set()
            # Persistence is complete before any rendering operation can fail.
            self.render_failed = True"""),
("            self._autosave()\n            self._controls()\n        elif kind == 'image':", "            self.render_failed = False\n            self._controls()\n        elif kind == 'image':"),
("            button.pack(side='left', padx=(0, 8))\n            self.choice_buttons.append(button)", "            button.pack(fill='x', pady=(0, 3))\n            self.choice_buttons.append(button)"),
("            save_state(self.save_path, self.state)\n        except (OSError, ValueError) as exc:", "            save_state(self.save_path, self.state)\n            self.save_dirty = False\n        except (OSError, ValueError) as exc:\n            self.save_dirty = True"),
("            self.image_label.image = photo\n        except Exception:", "            self.image_label.image = photo\n            return True\n        except Exception:"),
("            self.status_var.set(self.status_warning)\n\n    def retry(self):", "            self.status_var.set(self.status_warning)\n            self.state.image_key = ''\n            self.image_failed = True\n            return False\n\n    def retry(self):"),
("        if self.failed_action:\n            self._launch(self.failed_action)", """        if self.pending_scene:
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
            self._launch(self.failed_action)"""),
("    def resume(self):\n        if self.busy:\n            return", """    def resume(self, confirm=True):
        if self.busy:
            return
        if confirm and (self.pending_scene or self.save_dirty) and not messagebox.askyesno('Discard pending changes?', 'Resume will discard a scene or image reference that could not be saved. Continue?', parent=self.master):
            return"""),
("        if restored.image_key:\n            self._show_image(self.cache_dir / (restored.image_key + '.png'))\n        self.failed_action = None\n        self.image_failed = False\n        self.status_var.set('Saved adventure restored.' if not restored.finished else 'This saved adventure is complete. Start a new one to play again.')", """        self.failed_action = None
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
                self.image_label.configure(image='', text='Saved illustration is missing. Retry to paint it again.')
        self.status_var.set('Story restored. Retry to replace the missing illustration.' if self.image_failed else ('Saved adventure restored.' if not restored.finished else 'This saved adventure is complete. Start a new one to play again.'))"""),
("        if self.state.arrived and not messagebox.askyesno('New adventure?'", "        if (self.state.arrived or self.pending_scene or self.save_dirty) and not messagebox.askyesno('New adventure?'"),
("        self.state = StoryState()\n        self.failed_action = None\n        self.image_failed = False\n        self.action_var.set('')", "        self.state = StoryState()\n        self.failed_action = None\n        self.image_failed = False\n        self.pending_scene = None\n        self.render_failed = False\n        self.save_dirty = False\n        self.action_var.set('')"),
])

# Upgrade synthetic test images to actual valid PNG fixtures; no AI pixels are claimed.
edit('tests/test_images.py', [
("gen = ImageGenerator(Path(folder), Path(folder) / 'lora')", "gen = ImageGenerator(Path(folder), Path(folder) / 'lora', use_lora=False)"),
("            expected.write_bytes(b'cache fixture')", "            from PIL import Image\n            Image.new('RGB', (512, 512), 'navy').save(expected)"),
])
edit('tests/test_integration.py', [
("        return 'a' * 64, Path('nonexistent-test-image.png')", "        from PIL import Image\n        self.path.parent.mkdir(parents=True, exist_ok=True)\n        Image.new('RGB', (512, 512), 'navy').save(self.path)\n        return 'a' * 64, self.path"),
("        self.app.state = StoryState(name='Audit player', origin='Home')", "        self.images.path = self.app.cache_dir / ('a' * 64 + '.png')\n        self.app.state = StoryState(name='Audit player', origin='Home')"),
])
edit('tests/test_recovery_edges.py', [
("from test_integration import IntegrationTests", "import test_integration as helpers"),
("    setUp = IntegrationTests.setUp", "    setUp = helpers.IntegrationTests.setUp"),
("    tearDown = IntegrationTests.tearDown", "    tearDown = helpers.IntegrationTests.tearDown"),
("    spin = IntegrationTests.spin", "    spin = helpers.IntegrationTests.spin"),
])
