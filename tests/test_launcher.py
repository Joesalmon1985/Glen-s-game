"""Launcher readiness tests. No service is started in these unit tests."""
import importlib.util
from pathlib import Path
import sys
import types
from unittest.mock import patch
import pytest

ROOT = Path(__file__).resolve().parents[1]

def module():
    path = ROOT / 'scripts' / 'ensure_story.py'
    assert path.exists(), 'Missing self-starting local narrator launcher'
    spec = importlib.util.spec_from_file_location('ensure_story', path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m

def test_existing_ready_service_does_not_spawn_another():
    m = module()
    with patch.object(m, 'tags', return_value=['mistral:latest']), patch.object(m.subprocess, 'Popen') as spawn:
        m.ensure_ready(ROOT)
    spawn.assert_not_called()

def test_missing_model_is_not_declared_playable():
    m = module()
    with patch.object(m, 'tags', return_value=[]):
        with pytest.raises(RuntimeError, match='mistral'):
            m.ensure_ready(ROOT)
