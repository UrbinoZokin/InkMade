#!/usr/bin/env python3
"""Build a one-click, single-file InkyCal Setup executable with PyInstaller.

Usage:
    python -m pip install -r requirements.txt
    python build_executable.py

Output lands in ``dist/`` :
    * Windows -> dist/InkyCal-Setup.exe   (double-click to run)
    * macOS   -> dist/InkyCal-Setup       (a .app bundle is also produced)
    * Linux   -> dist/InkyCal-Setup

Run this on each OS you want to ship for; PyInstaller does not cross-compile.
"""
from __future__ import annotations

import sys
from importlib import metadata
from pathlib import Path

import PyInstaller.__main__
from packaging.requirements import Requirement

APP_NAME = "InkyCal-Setup"
REQUIREMENTS = Path(__file__).with_name("requirements.txt")


def _check_runtime_dependencies() -> None:
    """Stop the build if anything in requirements.txt isn't installed here.

    PyInstaller bundles only what it can import from the Python running it.
    A missing package isn't an error to it: it notes it in a warnings file,
    finishes "successfully", and the executable then dies on launch with
    ModuleNotFoundError. That happens whenever requirements.txt gains a
    dependency and the build environment isn't re-synced with it.
    """
    missing = []
    for line in REQUIREMENTS.read_text().splitlines():
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        req = Requirement(line)
        if req.marker is not None and not req.marker.evaluate():
            continue
        try:
            metadata.version(req.name)
        except metadata.PackageNotFoundError:
            missing.append(str(req))
    if missing:
        sys.exit(
            "Not building: these runtime dependencies aren't installed in the "
            "Python running this script, so the executable would crash on "
            "launch:\n  " + "\n  ".join(missing) + "\n\nInstall them with:\n  "
            f'"{sys.executable}" -m pip install -r "{REQUIREMENTS}"'
        )


def _bleak_backend_submodules() -> list[str]:
    """Collect only the BLE backend for the platform we're building on.

    bleak ships backends for Windows (winrt), macOS (corebluetooth) and
    Linux (bluezdbus). Collecting *all* of them (``--collect-submodules
    bleak``) makes PyInstaller import the foreign backends, which fails on
    the build host -- e.g. corebluetooth needs pyobjc (``objc``) and emits
    a warning on Windows/Linux. We only need the current platform's backend.
    """
    if sys.platform == "win32":
        pkg = "bleak.backends.winrt"
    elif sys.platform == "darwin":
        pkg = "bleak.backends.corebluetooth"
    else:
        pkg = "bleak.backends.bluezdbus"
    try:
        from PyInstaller.utils.hooks import collect_submodules
        return collect_submodules(pkg)
    except Exception:
        return [pkg]


def build() -> None:
    _check_runtime_dependencies()
    hidden_imports = [
        "bleak",
        "bleak.backends",
        *_bleak_backend_submodules(),
    ]
    args = [
        # Launch via a top-level script so the frozen entry point does not
        # run a package module as __main__ (which breaks relative imports).
        "launcher.py",
        "--name", APP_NAME,
        "--onefile",
        "--windowed",            # no console window for the GUI
        "--noconfirm",
        "--clean",
        # Bundle our whole package (cli/gui are imported lazily at runtime).
        "--collect-submodules", "inkycal_companion",
        # zeroconf has dynamically-imported / compiled submodules; collect them.
        "--collect-submodules", "zeroconf",
        "--collect-submodules", "google_auth_oauthlib",
    ]
    for mod in hidden_imports:
        args += ["--hidden-import", mod]
    PyInstaller.__main__.run(args)


if __name__ == "__main__":
    build()
