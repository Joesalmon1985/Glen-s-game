import subprocess
import sys
from pathlib import Path

def test_real_runtime_check_is_available_from_the_game_entry_point():
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run([sys.executable, str(root / 'my_version_of_kawa.py'), '--help'], capture_output=True, text=True, timeout=15)
    assert result.returncode == 0
    assert '--verify-startup' in result.stdout
