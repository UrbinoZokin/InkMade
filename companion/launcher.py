#!/usr/bin/env python3
"""Frozen-app entry point for PyInstaller.

PyInstaller runs the entry script as top-level ``__main__`` with no parent
package, which breaks the relative imports inside the package. We therefore
launch via an absolute import of ``inkycal_companion.__main__`` -- imported as
a proper submodule, its relative imports resolve correctly.

For running from source, use ``python -m inkycal_companion`` instead.
"""
from inkycal_companion.__main__ import main

if __name__ == "__main__":
    raise SystemExit(main())
