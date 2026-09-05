"""Read-only preflight checks for the Puca Python game.

This module intentionally uses only the Python standard library.  It can run in
an empty environment and reports machine-readable JSON instead of attempting to
repair, install, download, or start anything.
"""

from __future__ import annotations

import argparse
import importlib
import importlib.metadata
import importlib.util
import json
import platform
import shutil
import sys
import urllib.error
import urllib.request
from typing import Any, Callable, Mapping


DIAGNOSTICS_VERSION = 1
OLLAMA_DEFAULT_URL = "http://127.0.0.1:11434/api/tags"
OLLAMA_MODEL = "mistral"
SUPPORTED_PYTHON = "3.11-3.13"
SUPPORTED_PYTHON_MIN = (3, 11)
SUPPORTED_PYTHON_MAX_EXCLUSIVE = (3, 14)

# The full game may use the GPU/image stack, while text-only mode can omit it.
# It remains optional to diagnostics, so this module never depends on any of it.
REQUIRED_PACKAGES = {
    "requests": {
        "distribution": "requests",
        "import_name": "requests",
        "expected_version": "2.32.3",
    },
    "Pillow": {
        "distribution": "Pillow",
        "import_name": "PIL",
        "expected_version": "11.3.0",
    },
    "pywin32": {
        "distribution": "pywin32",
        "import_name": "win32com",
        "expected_version": "311",
    },
}

OPTIONAL_PACKAGES = {
    "torch": {
        "distribution": "torch",
        "import_name": "torch",
        "expected_version": "2.7.1",
    },
    "diffusers": {
        "distribution": "diffusers",
        "import_name": "diffusers",
        "expected_version": "0.35.2",
    },
    "transformers": {
        "distribution": "transformers",
        "import_name": "transformers",
        "expected_version": "4.57.3",
    },
    "peft": {
        "distribution": "peft",
        "import_name": "peft",
        "expected_version": "0.18.0",
    },
    "accelerate": {
        "distribution": "accelerate",
        "import_name": "accelerate",
        "expected_version": "1.12.0",
    },
}

_AUTO = object()


def _version_text(version: Any) -> str | None:
    """Return a JSON-safe version string, or None when unavailable."""

    if version is None:
        return None
    return str(version)


def check_python_version(
    version: Any = None,
    *,
    is_64_bit: bool | None = None,
) -> dict[str, Any]:
    """Check for a supported 64-bit 3.11-3.13 interpreter."""

    if version is None:
        version = sys.version_info
    if is_64_bit is None:
        is_64_bit = sys.maxsize > 2**32
    try:
        major, minor, micro = (int(version[0]), int(version[1]), int(version[2]))
    except (IndexError, TypeError, ValueError):
        return {
            "status": "error",
            "version": None,
            "is_64_bit": bool(is_64_bit),
            "supported": SUPPORTED_PYTHON,
            "message": "Could not read the Python version.",
        }

    supported = (
        (major, minor) >= SUPPORTED_PYTHON_MIN
        and (major, minor) < SUPPORTED_PYTHON_MAX_EXCLUSIVE
        and bool(is_64_bit)
    )
    return {
        "status": "supported" if supported else "unsupported",
        "version": f"{major}.{minor}.{micro}",
        "major": major,
        "minor": minor,
        "micro": micro,
        "is_64_bit": bool(is_64_bit),
        "supported": SUPPORTED_PYTHON,
        "message": (
            "Supported 64-bit Python interpreter."
            if supported
            else "Use a 64-bit Python 3.11, 3.12, or 3.13 interpreter; Python 3.14 and 32-bit Python are not supported."
        ),
    }


def _torch_import() -> Any:
    try:
        return importlib.import_module("torch")
    except ModuleNotFoundError:
        return None


def check_torch(torch_module: Any = _AUTO) -> dict[str, Any]:
    """Report Torch build/runtime state without installing or changing anything.

    ``cpu_only`` means the installed wheel has no CUDA build.  A CUDA wheel with
    a driver/runtime problem is reported separately as ``cuda_unavailable``.
    When available, a one-element CUDA tensor is created as a lightweight proof
    that the runtime can actually execute work.
    """

    if torch_module is _AUTO:
        try:
            torch_module = _torch_import()
        except Exception as exc:  # pragma: no cover - defensive import boundary
            return {
                "status": "import_error",
                "torch_version": None,
                "cuda_build": None,
                "cuda_available": False,
                "device_count": 0,
                "device_names": [],
                "tensor_test": "not_run",
                "error": f"{type(exc).__name__}: {exc}",
            }

    if torch_module is None:
        return {
            "status": "missing",
            "torch_version": None,
            "cuda_build": None,
            "cuda_available": False,
            "device_count": 0,
            "device_names": [],
            "tensor_test": "not_run",
            "message": "Torch is not installed in this interpreter.",
        }

    torch_version = _version_text(getattr(torch_module, "__version__", None))
    torch_version_info = getattr(torch_module, "version", None)
    cuda_build = _version_text(getattr(torch_version_info, "cuda", None))

    if not cuda_build:
        return {
            "status": "cpu_only",
            "torch_version": torch_version,
            "cuda_build": None,
            "cuda_available": False,
            "device_count": 0,
            "device_names": [],
            "tensor_test": "not_run",
            "message": "Torch is CPU-only; install the official cu128 wheel in .venv.",
        }

    cuda = getattr(torch_module, "cuda", None)
    try:
        cuda_available = bool(cuda is not None and cuda.is_available())
    except Exception as exc:
        return {
            "status": "cuda_unavailable",
            "torch_version": torch_version,
            "cuda_build": cuda_build,
            "cuda_available": False,
            "device_count": 0,
            "device_names": [],
            "tensor_test": "not_run",
            "error": f"CUDA availability check failed: {type(exc).__name__}: {exc}",
            "message": "Torch has CUDA support, but the CUDA runtime/driver is unavailable.",
        }

    if not cuda_available:
        return {
            "status": "cuda_unavailable",
            "torch_version": torch_version,
            "cuda_build": cuda_build,
            "cuda_available": False,
            "device_count": 0,
            "device_names": [],
            "tensor_test": "not_run",
            "message": "Torch has CUDA support, but no usable CUDA device is available.",
        }

    try:
        device_count = int(cuda.device_count())
    except Exception:
        device_count = 0

    device_names: list[str] = []
    for index in range(max(0, device_count)):
        try:
            device_names.append(str(cuda.get_device_name(index)))
        except Exception as exc:
            device_names.append(f"<unavailable: {type(exc).__name__}>")

    tensor_test = "not_run"
    tensor_error = None
    zeros = getattr(torch_module, "zeros", None)
    if callable(zeros):
        try:
            sample = zeros(1, device="cuda")
            # Materialise one value so lazy backends cannot report a false pass.
            if hasattr(sample, "item"):
                sample.item()
            del sample
            tensor_test = "passed"
        except Exception as exc:
            tensor_test = "failed"
            tensor_error = f"{type(exc).__name__}: {exc}"

    result: dict[str, Any] = {
        "status": "cuda_ready" if tensor_test != "failed" else "cuda_unavailable",
        "torch_version": torch_version,
        "cuda_build": cuda_build,
        "cuda_available": True,
        "device_count": device_count,
        "device_names": device_names,
        "tensor_test": tensor_test,
        "message": (
            "CUDA is available and passed the tiny tensor test."
            if tensor_test == "passed"
            else "CUDA is available; the injected diagnostic double did not expose a tensor test."
            if tensor_test == "not_run"
            else "CUDA reported available, but the tiny tensor test failed."
        ),
    }
    if tensor_error:
        result["error"] = tensor_error
    return result


def _inspect_one_package(
    name: str,
    spec: Mapping[str, str],
    find_spec: Callable[[str], Any],
    version_getter: Callable[[str], Any],
) -> dict[str, Any]:
    record: dict[str, Any] = {
        "distribution": spec["distribution"],
        "import_name": spec["import_name"],
        "expected_version": spec["expected_version"],
        "installed_version": None,
        "status": "missing",
    }
    try:
        present = find_spec(spec["import_name"]) is not None
    except Exception as exc:
        record["status"] = "error"
        record["error"] = f"Import lookup failed: {type(exc).__name__}: {exc}"
        return record

    if not present:
        return record

    record["status"] = "installed"
    try:
        record["installed_version"] = _version_text(version_getter(spec["distribution"]))
        if record["installed_version"] is None:
            record["version_status"] = "unknown"
        elif name == "torch" and record["installed_version"].startswith(
            spec["expected_version"] + "+"
        ):
            # CUDA wheels carry a local version suffix such as +cu128.
            record["version_status"] = "match"
        else:
            record["version_status"] = (
                "match"
                if record["installed_version"] == spec["expected_version"]
                else "mismatch"
            )
    except Exception as exc:
        # An importable package may be an editable checkout or another unusual
        # install.  Keep it installed, but make the missing metadata explicit.
        record["version_status"] = "unknown"
        record["version_error"] = f"{type(exc).__name__}: {exc}"
    return record


def inspect_packages(
    *,
    find_spec: Callable[[str], Any] | None = None,
    version_getter: Callable[[str], Any] | None = None,
) -> dict[str, Any]:
    """Inspect required and optional distributions without importing them."""

    find_spec = find_spec or importlib.util.find_spec
    version_getter = version_getter or importlib.metadata.version
    required: dict[str, Any] = {}
    optional: dict[str, Any] = {}
    for name, spec in REQUIRED_PACKAGES.items():
        required[name] = _inspect_one_package(name, spec, find_spec, version_getter)
    for name, spec in OPTIONAL_PACKAGES.items():
        optional[name] = _inspect_one_package(name, spec, find_spec, version_getter)

    all_packages = {**required, **optional}
    return {
        "required": required,
        "optional": optional,
        "missing_required": [
            name for name, record in required.items() if record["status"] != "installed"
        ],
        "missing_optional": [
            name for name, record in optional.items() if record["status"] != "installed"
        ],
        "version_mismatches": [
            name
            for name, record in all_packages.items()
            if record.get("version_status") == "mismatch"
        ],
    }


def _ollama_model_status(models: list[str], requested_model: str) -> str:
    for name in models:
        if name == requested_model or name.startswith(requested_model + ":"):
            return "installed"
    return "missing"


def check_ollama(
    *,
    url: str = OLLAMA_DEFAULT_URL,
    model: str = OLLAMA_MODEL,
    timeout: float = 2.0,
    which: Callable[[str], str | None] | None = None,
    urlopen: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    """Read Ollama's local tags endpoint; never installs or pulls a model."""

    which = which or shutil.which
    urlopen = urlopen or urllib.request.urlopen
    try:
        executable_path = which("ollama")
    except Exception as exc:
        executable_path = None
        executable_error = f"{type(exc).__name__}: {exc}"
    else:
        executable_error = None

    result: dict[str, Any] = {
        "status": "not_installed",
        "executable": bool(executable_path),
        "executable_path": executable_path,
        "service": "unreachable",
        "model": model,
        "model_status": "unknown",
        "models": [],
        "url": url,
        "message": "Ollama is not installed; install it separately for story play.",
    }
    if executable_error:
        result["executable_error"] = executable_error

    request = urllib.request.Request(url, headers={"Accept": "application/json"}, method="GET")
    try:
        with urlopen(request, timeout=timeout) as response:
            raw = response.read()
        payload = json.loads(raw.decode("utf-8"))
        raw_models = payload.get("models", []) if isinstance(payload, dict) else []
        models = [
            str(item.get("name"))
            for item in raw_models
            if isinstance(item, dict) and item.get("name")
        ]
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        result["service"] = "unreachable"
        result["message"] = (
            "Ollama is installed but not running; start it separately and ensure the mistral model is available."
            if executable_path
            else "Ollama is not installed or its local service is not running."
        )
        result["error"] = f"{type(exc).__name__}: {exc}"
        result["status"] = "not_running" if executable_path else "not_installed"
        return result
    except (ValueError, UnicodeError, AttributeError, KeyError, TypeError) as exc:
        result["service"] = "error"
        result["status"] = "error"
        result["message"] = "Ollama responded, but its tags response was not valid JSON."
        result["error"] = f"{type(exc).__name__}: {exc}"
        return result

    result["service"] = "reachable"
    result["models"] = models
    result["model_status"] = _ollama_model_status(models, model)
    result["status"] = "available"
    result["message"] = (
        f"Ollama is running and {model!r} is installed."
        if result["model_status"] == "installed"
        else f"Ollama is running, but {model!r} is not installed; pull it separately if needed."
    )
    return result


def _overall_status(
    python_result: Mapping[str, Any],
    torch_result: Mapping[str, Any],
    packages_result: Mapping[str, Any],
    ollama_result: Mapping[str, Any],
) -> str:
    if python_result.get("status") in {"unsupported", "error"}:
        return "error"
    if packages_result.get("missing_required"):
        return "error"
    if packages_result.get("version_mismatches"):
        return "error"
    if torch_result.get("status") in {"missing", "cpu_only", "import_error"}:
        return "error"

    warnings = bool(packages_result.get("missing_optional"))
    if torch_result.get("status") != "cuda_ready":
        warnings = True
    # Ollama is intentionally optional: its absence is a warning, not an
    # installer failure, because text-only operation may not need it.
    if ollama_result.get("status") not in {"available", "skipped"}:
        warnings = True
    return "warning" if warnings else "ok"


def run_diagnostics(
    *,
    python_version: Any = None,
    is_64_bit: bool | None = None,
    torch_module: Any = _AUTO,
    find_spec: Callable[[str], Any] | None = None,
    version_getter: Callable[[str], Any] | None = None,
    which: Callable[[str], str | None] | None = None,
    urlopen: Callable[..., Any] | None = None,
    ollama_url: str = OLLAMA_DEFAULT_URL,
    ollama_timeout: float = 2.0,
    skip_ollama: bool = False,
) -> dict[str, Any]:
    """Return the stable, JSON-serializable diagnostic document."""

    python_result = check_python_version(
        python_version,
        is_64_bit=is_64_bit,
    )
    torch_result = check_torch(torch_module)
    packages_result = inspect_packages(find_spec=find_spec, version_getter=version_getter)
    if skip_ollama:
        ollama_result = {
            "status": "skipped",
            "executable": None,
            "executable_path": None,
            "service": "skipped",
            "model": OLLAMA_MODEL,
            "model_status": "unknown",
            "models": [],
            "url": ollama_url,
            "message": "Ollama check was skipped.",
        }
    else:
        ollama_result = check_ollama(
            url=ollama_url,
            timeout=ollama_timeout,
            which=which,
            urlopen=urlopen,
        )

    return {
        "diagnostics_version": DIAGNOSTICS_VERSION,
        "python": python_result,
        "torch": torch_result,
        "packages": packages_result,
        "ollama": ollama_result,
        "overall_status": _overall_status(
            python_result, torch_result, packages_result, ollama_result
        ),
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Read-only Puca environment diagnostics")
    parser.add_argument(
        "--skip-ollama",
        action="store_true",
        help="Do not contact Ollama's local read-only tags endpoint",
    )
    parser.add_argument(
        "--ollama-url",
        default=OLLAMA_DEFAULT_URL,
        help="Ollama tags endpoint (default: %(default)s)",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=2.0,
        help="Ollama check timeout in seconds (default: %(default)s)",
    )
    parser.add_argument(
        "--require-ollama",
        action="store_true",
        help="Return exit code 1 unless Ollama and the mistral model are available",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Return exit code 1 when the diagnostic overall status is not ok",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    result = run_diagnostics(
        ollama_url=args.ollama_url,
        ollama_timeout=max(0.1, args.timeout),
        skip_ollama=args.skip_ollama,
    )
    # Keep stdout as one JSON document so batch files and support scripts can
    # consume it.  Diagnostics are read-only and should never print progress.
    print(json.dumps(result, indent=2, sort_keys=True))
    ollama_ok = (
        result["ollama"].get("status") == "available"
        and result["ollama"].get("model_status") == "installed"
    )
    if args.require_ollama and not ollama_ok:
        return 1
    if args.strict and result["overall_status"] != "ok":
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
