#!/usr/bin/env python3
"""Build a one-click, single-file InkyCal Setup executable with PyInstaller.

Usage:
    pip install -r requirements.txt pyinstaller
    python build_executable.py

Output lands in ``dist/`` :
    * Windows -> dist/InkyCal-Setup.exe   (double-click to run)
    * macOS   -> dist/InkyCal-Setup       (a .app bundle is also produced)
    * Linux   -> dist/InkyCal-Setup

Run this on each OS you want to ship for; PyInstaller does not cross-compile.
"""
from __future__ import annotations

import PyInstaller.__main__

APP_NAME = "InkyCal-Setup"


def build() -> None:
    args = [
        "inkycal_companion/__main__.py",
        "--name", APP_NAME,
        "--onefile",
        "--windowed",            # no console window for the GUI
        "--noconfirm",
        "--clean",
        # bleak / zeroconf pull in platform backends via dynamic imports;
        # collect them so the frozen build can find them.
        "--collect-submodules", "bleak",
        "--collect-submodules", "zeroconf",
        "--collect-submodules", "google_auth_oauthlib",
        "--hidden-import", "inkycal_companion.cli",
        "--hidden-import", "inkycal_companion.gui",
    ]
    PyInstaller.__main__.run(args)


if __name__ == "__main__":
    build()
