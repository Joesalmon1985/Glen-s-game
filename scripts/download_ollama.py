"""Fetch and verify the official portable runtime without changing PATH or services."""
import hashlib
import json
from pathlib import Path
import urllib.request
import zipfile

root = Path(__file__).resolve().parents[1]
runtime = root / '.runtime' / 'ollama'
archive = root / '.runtime' / 'ollama-v0.33.3.zip'
runtime.mkdir(parents=True, exist_ok=True)
url = 'https://github.com/ollama/ollama/releases/download/v0.33.3/ollama-windows-amd64.zip'
expected_size = 1469175900
expected_sha256 = '52cb36a62e7e501f61514f60212dec7117b6c098811357585e02fffe32d2fcd7'
for attempt in range(3):
    offset = archive.stat().st_size if archive.exists() else 0
    if offset == expected_size:
        break
    request = urllib.request.Request(url, headers={'Range': f'bytes={offset}-'} if offset else {})
    with urllib.request.urlopen(request, timeout=120) as response:
        append = offset and response.status == 206
        if append and not response.headers.get('Content-Range', '').startswith(f'bytes {offset}-'):
            raise RuntimeError('Download range mismatch')
        with archive.open('ab' if append else 'wb') as output:
            while block := response.read(4 * 1024 * 1024):
                output.write(block)
    print('Downloaded bytes:', archive.stat().st_size, flush=True)
if archive.stat().st_size != expected_size:
    raise RuntimeError('Incomplete download. Run this script again to resume.')
with archive.open('rb') as source:
    actual = hashlib.file_digest(source, 'sha256').hexdigest()
if actual != expected_sha256:
    raise RuntimeError('Official SHA-256 mismatch; runtime will not be extracted or executed.')
with zipfile.ZipFile(archive) as package:
    for member in package.infolist():
        target = (runtime / member.filename).resolve()
        if not target.is_relative_to(runtime.resolve()):
            raise RuntimeError('Unsafe archive path')
    package.extractall(runtime)
assert (runtime / 'ollama.exe').is_file()
print(json.dumps({'runtime': str(runtime), 'archive_bytes': archive.stat().st_size, 'sha256': actual, 'source': url}), flush=True)
