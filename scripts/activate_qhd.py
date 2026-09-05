"""Activate only a QHD executable whose own real runtime check passed."""
from pathlib import Path
import hashlib
import json
import win32com.client

root = Path(__file__).resolve().parents[1]
exe = root / 'dist-qhd/Puca/Puca.exe'
launcher = root / 'Play Puca.bat'
reports = sorted((root / 'docs/verification/qhd-exe').glob('runtime-check-*/runtime-report.json'), key=lambda p:p.stat().st_mtime)
assert exe.is_file() and reports, 'QHD build and real runtime report are required'
proof = json.loads(reports[-1].read_text())
with exe.open('rb') as stream:
    digest = hashlib.file_digest(stream, 'sha256').hexdigest()
assert proof['success'] and proof['frozen'] and proof['adapter_loaded']
assert proof['turn'] == 1 and proof['history_records'] == 2
assert proof['client_pixels'] == proof['native_client_pixels'] == [2560, 1440]
assert proof['displayed_art_pixels'] == [768, 768]
assert digest == proof['executable_sha256'], 'Executable differs from its tested build'
text = launcher.read_text()
assert 'dist-qhd\\Puca\\Puca.exe' in text and 'dist-qhd\\Puca\\VERIFIED.json' in text
assert 'dist\\Puca\\' not in text
receipt = {'success': True, 'executable_sha256': digest, 'runtime_report': str(reports[-1]), 'client_pixels': proof['native_client_pixels']}
marker = exe.parent / 'VERIFIED.json'
marker.write_text(json.dumps(receipt, indent=2), encoding='utf-8')
assert json.loads(marker.read_text()) == receipt
shell = win32com.client.Dispatch('WScript.Shell')
desktop = Path(shell.SpecialFolders('Desktop'))
shortcuts = []
for path in (desktop / 'Puca - Play.lnk', root / 'START PUCA.lnk'):
    link = shell.CreateShortcut(str(path))
    link.TargetPath = str(launcher)
    link.WorkingDirectory = str(root)
    link.IconLocation = str(exe) + ',0'
    link.Description = 'Play Puca at 2560 x 1440; starts the local narrator automatically'
    link.Save()
    check = shell.CreateShortcut(str(path))
    assert path.is_file() and Path(check.TargetPath).resolve() == launcher.resolve()
    assert Path(check.WorkingDirectory).resolve() == root.resolve()
    assert check.IconLocation == str(exe) + ',0'
    shortcuts.append(str(path))
print(json.dumps({'success': True, 'executable': str(exe), 'native_client_pixels': proof['native_client_pixels'], 'art_pixels': proof['displayed_art_pixels'], 'shortcuts': shortcuts, 'runtime_report': str(reports[-1])}, indent=2))
