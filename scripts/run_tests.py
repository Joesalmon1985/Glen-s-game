"""Run every collected test once. Native Tk gets a fresh interpreter per case.
This avoids cross-test Tcl teardown contamination; the game itself creates one Tk root.
No failures are retried or hidden. The report preserves each command and its output.
"""
import json
from pathlib import Path
import subprocess
import sys

root = Path(__file__).resolve().parents[1]
report = root / 'docs' / 'verification'
report.mkdir(parents=True, exist_ok=True)
collection = subprocess.run([sys.executable, '-m', 'pytest', 'tests', '--collect-only', '-q'], cwd=root, capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=120)
if collection.returncode:
    print(collection.stdout + collection.stderr)
    raise SystemExit(collection.returncode)
nodes = [line.strip() for line in collection.stdout.splitlines() if line.startswith('tests/') and '::' in line]
if not nodes or len(nodes) != len(set(nodes)):
    raise RuntimeError('Invalid or empty test inventory')
results = []
for node in nodes:
    result = subprocess.run([sys.executable, '-m', 'pytest', node, '-q'], cwd=root, capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=120)
    results.append({'test':node, 'exit_code':result.returncode, 'output':result.stdout + result.stderr})
    (report / 'tests.json').write_text(json.dumps(results, indent=2), encoding='utf-8')
    print(('PASS ' if result.returncode == 0 else 'FAIL ') + node, flush=True)
failed = [r['test'] for r in results if r['exit_code'] != 0]
print(json.dumps({'collected':len(nodes), 'executed':len(results), 'passed':len(results)-len(failed), 'failed':failed}), flush=True)
raise SystemExit(bool(failed))
