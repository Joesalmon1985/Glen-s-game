"""TDD coverage for the dependency/GPU/Ollama preflight diagnostics."""

from __future__ import annotations

import json
from types import SimpleNamespace
from urllib.error import URLError

import diagnostics


class _Cuda:
    def __init__(self, available: bool):
        self._available = available

    def is_available(self):
        return self._available

    def device_count(self):
        return 1 if self._available else 0

    def get_device_name(self, index):
        return "Test RTX 3060 Ti"


class _Response:
    def __init__(self, payload):
        self._payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return json.dumps(self._payload).encode("utf-8")


def _torch(cuda_build, cuda_available):
    return SimpleNamespace(
        __version__="2.7.1+cu128",
        version=SimpleNamespace(cuda=cuda_build),
        cuda=_Cuda(cuda_available),
    )


def test_supported_python_versions_are_explicitly_supported():
    assert diagnostics.check_python_version((3, 11, 9))["status"] == "supported"
    assert diagnostics.check_python_version((3, 13, 6))["status"] == "supported"


def test_python_314_is_rejected_before_installation():
    result = diagnostics.check_python_version((3, 14, 0))
    assert result["status"] == "unsupported"
    assert result["supported"] == "3.11-3.13"


def test_32_bit_supported_version_is_rejected():
    result = diagnostics.check_python_version((3, 13, 0), is_64_bit=False)
    assert result["status"] == "unsupported"
    assert result["is_64_bit"] is False


def test_cpu_only_torch_is_distinguished_from_runtime_cuda_failure():
    result = diagnostics.check_torch(_torch(None, False))
    assert result["status"] == "cpu_only"
    assert result["cuda_build"] is None
    assert result["cuda_available"] is False


def test_cuda_build_without_working_runtime_is_reported_as_unavailable():
    result = diagnostics.check_torch(_torch("12.8", False))
    assert result["status"] == "cuda_unavailable"
    assert result["cuda_build"] == "12.8"
    assert result["cuda_available"] is False


def test_working_cuda_reports_device_details():
    result = diagnostics.check_torch(_torch("12.8", True))
    assert result["status"] == "cuda_ready"
    assert result["cuda_available"] is True
    assert result["device_count"] == 1
    assert result["device_names"] == ["Test RTX 3060 Ti"]


def test_missing_optional_packages_are_listed_without_importing_them():
    present = {"requests", "PIL", "win32com"}

    def fake_find_spec(name):
        return object() if name in present else None

    def fake_version(name):
        return {"requests": "2.32.3", "Pillow": "11.3.0", "pywin32": "311"}[name]

    result = diagnostics.inspect_packages(
        find_spec=fake_find_spec,
        version_getter=fake_version,
    )
    assert result["required"]["requests"]["status"] == "installed"
    assert result["required"]["Pillow"]["status"] == "installed"
    assert result["optional"]["diffusers"]["status"] == "missing"
    assert "diffusers" in result["missing_optional"]


def test_installed_but_wrong_package_version_is_reported_as_drift():
    def present(_name):
        return object()

    def wrong_version(name):
        return "9.9.9" if name == "requests" else "11.3.0"

    result = diagnostics.inspect_packages(
        find_spec=present,
        version_getter=wrong_version,
    )
    assert result["required"]["requests"]["status"] == "installed"
    assert result["required"]["requests"]["version_status"] == "mismatch"
    assert "requests" in result["version_mismatches"]


def test_ollama_is_checked_read_only_and_missing_is_actionable():
    def no_ollama(_name):
        return None

    def offline(_request, timeout):
        raise URLError("connection refused")

    result = diagnostics.check_ollama(which=no_ollama, urlopen=offline)
    assert result["status"] == "not_installed"
    assert result["executable"] is False
    assert result["service"] == "unreachable"
    assert result["model"] == "mistral"
    assert result["model_status"] == "unknown"


def test_ollama_service_and_mistral_are_detected_without_pulling():
    result = diagnostics.check_ollama(
        which=lambda _name: "C:/Ollama/ollama.exe",
        urlopen=lambda _request, timeout: _Response(
            {"models": [{"name": "mistral:latest"}, {"name": "other"}]}
        ),
    )
    assert result["status"] == "available"
    assert result["executable"] is True
    assert result["service"] == "reachable"
    assert result["model_status"] == "installed"
    assert result["models"] == ["mistral:latest", "other"]


def test_require_ollama_cli_rejects_missing_service():
    warning_result = {
        "diagnostics_version": 1,
        "python": {},
        "torch": {},
        "packages": {},
        "ollama": {"status": "not_running", "model_status": "unknown"},
        "overall_status": "warning",
    }
    original = diagnostics.run_diagnostics
    diagnostics.run_diagnostics = lambda **_kwargs: warning_result
    try:
        assert diagnostics.main(["--require-ollama"]) == 1
    finally:
        diagnostics.run_diagnostics = original


def test_strict_cli_rejects_warning_status():
    warning_result = {
        "diagnostics_version": 1,
        "python": {},
        "torch": {},
        "packages": {},
        "ollama": {},
        "overall_status": "warning",
    }
    original = diagnostics.run_diagnostics
    diagnostics.run_diagnostics = lambda **_kwargs: warning_result
    try:
        assert diagnostics.main(["--skip-ollama", "--strict"]) == 1
    finally:
        diagnostics.run_diagnostics = original


def test_diagnostics_result_is_json_serializable_and_has_exact_top_level_shape():
    result = diagnostics.run_diagnostics(
        python_version=(3, 13, 0),
        torch_module=_torch("12.8", True),
        find_spec=lambda _name: None,
        version_getter=lambda _name: None,
        which=lambda _name: None,
        urlopen=lambda _request, timeout: (_ for _ in ()).throw(
            URLError("connection refused")
        ),
    )
    encoded = json.dumps(result, sort_keys=True)
    decoded = json.loads(encoded)
    assert set(decoded) == {
        "diagnostics_version",
        "python",
        "torch",
        "packages",
        "ollama",
        "overall_status",
    }
    assert decoded["diagnostics_version"] == 1
    assert decoded["overall_status"] in {"ok", "warning", "error"}
