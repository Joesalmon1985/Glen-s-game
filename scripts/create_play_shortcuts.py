"""Expose the tested executable through the existing narrator-aware launcher."""
from pathlib import Path
import hashlib
import json
import win32com.client

root = Path(__file__).resolve().parents[1]
exe = root / 'dist/Puca/Puca.exe'
launcher = root / 'Play Puca.bat'
reports = sorted((root / 'docs/verification/exe-proof').glob('runtime-check-*/runtime-report.json'), key=lambda p:p.stat().st_mtime)
assert exe.is_file() and launcher.is_file() and reports
proof = json.loads(reports[-1].read_text())
with exe.open('rb') as stream:
    digest = hashlib.file_digest(stream, 'sha256').hexdigest()
assert proof['success'] and proof['frozen'] and proof['adapter_loaded']
assert proof['turn'] == 1 and proof['history_records'] == 2
assert digest == proof['executable_sha256'], 'Executable differs from the tested build'
marker = exe.parent / 'VERIFIED.json'
receipt = {'success': True, 'executable_sha256': digest, 'runtime_report': str(reports[-1])}
marker.write_text(json.dumps(receipt, indent=2), encoding='utf-8')
assert json.loads(marker.read_text()) == receipt

shell = win32com.client.Dispatch('WScript.Shell')
desktop = Path(shell.SpecialFolders('Desktop'))
results = []
for path in (desktop / 'Puca - Play.lnk', root / 'START PUCA.lnk'):
    shortcut = shell.CreateShortcut(str(path))
    shortcut.TargetPath = str(launcher)
    shortcut.WorkingDirectory = str(root)
    shortcut.IconLocation = str(exe) + ',0'
    shortcut.Description = 'Start the local narrator and play the verified Puca game'
    shortcut.WindowStyle = 1
    shortcut.Save()
    check = shell.CreateShortcut(str(path))
    assert path.is_file()
    assert Path(check.TargetPath).resolve() == launcher.resolve()
    assert Path(check.WorkingDirectory).resolve() == root.resolve()
    results.append({'shortcut': str(path), 'target': check.TargetPath, 'icon': check.IconLocation})
print(json.dumps({'verified_exe': str(exe), 'shortcuts': results}, indent=2))
