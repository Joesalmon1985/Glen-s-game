"""Finalize only against actual passing runtime reports; never invent release receipts."""
from pathlib import Path
import hashlib
import json
import subprocess
import zipfile

root = Path(__file__).resolve().parents[1]
out = root / 'docs/verification'
tests = json.loads((out / 'tests.json').read_text())
assert len(tests) == 42 and all(t['exit_code'] == 0 for t in tests)
live = json.loads((out / 'live-playthrough.json').read_text())
assert live['success'] and live['turn'] == 10 and live['history_records'] == 11 and live['resume_verified']
gpu = json.loads((out / 'gpu.json').read_text())
assert gpu['success'] and gpu['adapter_loaded']
reports = sorted((out / 'exe-proof').glob('runtime-check-*/runtime-report.json'), key=lambda p:p.stat().st_mtime)
assert reports, 'Packaged runtime has not produced a report'
smoke = json.loads(reports[-1].read_text())
assert smoke['success'] and smoke['frozen'] and smoke['turn'] == 1 and smoke['history_records'] == 2 and smoke['adapter_loaded'], smoke
exe = root / 'dist/Puca/Puca.exe'
with exe.open('rb') as stream:
    sha = hashlib.file_digest(stream,'sha256').hexdigest()
assert sha == smoke['executable_sha256'], 'The tested executable is not the current executable'
receipt = {'success':True, 'executable_sha256':sha, 'runtime_report':str(reports[-1]),
           'regression_tests':len(tests), 'source_playthrough':str(out/'live-playthrough.json'),
           'GPU':gpu['GPU'], 'target_3060Ti_benchmarked':False}
(root / 'dist/Puca/VERIFIED.json').write_text(json.dumps(receipt,indent=2),encoding='utf-8')
freeze = subprocess.run(['uv','pip','freeze','--python',str(root/'.venv/Scripts/python.exe')],capture_output=True,text=True,check=True)
(out / 'environment.txt').write_text(freeze.stdout,encoding='utf-8')
readme = root/'README.md'
readme.write_text(readme.read_text().replace('**41 regression tests passed**','**42 regression tests passed**'),encoding='utf-8')
setup = root/'SETUP.md'
s = setup.read_text()
s = s.replace('installs `torch==2.7.1` from', 'installs `torch==2.7.1+cu128` from')
s = s.replace("The installer was not run\nhere, so no large Torch/model download or CUDA installation is claimed as\ncompleted, and CUDA runtime behavior was not verified on either target GPU.", "The final pass installed these dependencies into an isolated Python 3.13 environment using uv, downloaded the real AI weights, and verified CUDA, narration and illustrations on the RTX 5060 laptop. The batch installer itself has not been exercised from a clean customer PC. The exact tested package set is recorded in `docs/verification/environment.txt`.")
s += '\n## Ready installation in this folder\n\nOn this machine, double-click **Play Puca.bat**. The isolated Python runtime, local Ollama runtime and Mistral weights are installed. The launcher starts the local narrator if necessary and uses the verified new EXE. The old root-level EXE is unchanged.\n\nThe new EXE is `dist/Puca/Puca.exe`; keep its entire folder together. AI weights and the narrator service are not bundled into it. For a fresh PC, follow the install and Ollama steps above; do not transfer `.venv`.\n\nAn optional real runtime check is `Play Puca.bat --verify-startup`. It generates real narration and art, exercises a choice and Resume, writes a `runtime-report.json` inside a separate `runtime-check-*` save folder, then closes. It never overwrites your normal adventure.\n'
setup.write_text(s,encoding='utf-8')
(root/'TODO.md').write_text('''# Puca follow-up

- [x] Repair rules, saves, retries, UI, AI output handling and image efficiency.
- [x] Verify real narration, LoRA images and full source playthrough.
- [x] Build and exercise the new EXE; preserve originals.
- [ ] Benchmark the RTX 3060 Ti/i3 desktop before claiming its speed or memory floor.
- [ ] Optional next pass: authored story structure and a properly evaluated/retrained art adapter.
''',encoding='utf-8')
archive = root/'Puca-source.zip'
files = [*root.glob('*.py'), *root.glob('*.bat'), root/'requirements.txt', root/'Puca.spec', root/'README.md', root/'SETUP.md', root/'TODO.md', root/'docs/AUDIT.md']
files += list((root/'tests').glob('*.py'))
files += [root/'scripts'/name for name in ('download_ollama.py','ensure_story.py','run_tests.py','live_image_proof.py','live_playthrough.py')]
files += list((root/'pixel_style_lora_style_only').glob('*'))
files = sorted({p for p in files if p.is_file()})
with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as package:
    for path in files:
        package.write(path,path.relative_to(root))
with zipfile.ZipFile(archive) as package:
    assert package.testzip() is None
    assert len(package.namelist()) == len(files)
receipt.update({'source_archive':str(archive),'source_archive_bytes':archive.stat().st_size,'source_archive_files':len(files),
                'runtime_screenshot':smoke.get('screenshot')})
(out/'release.json').write_text(json.dumps(receipt,indent=2),encoding='utf-8')
print(json.dumps(receipt,indent=2))
