"""Entry point: launch the GUI by default, or the CLI with --cli/args."""
from __future__ import annotations

import sys


def main() -> int:
    argv = sys.argv[1:]
    if "--cli" in argv:
        argv.remove("--cli")
        from .cli import main as cli_main
        return cli_main(argv)
    # Any explicit CLI flags also imply headless mode.
    if any(a.startswith("--") for a in argv):
        from .cli import main as cli_main
        return cli_main(argv)
    from .gui import main as gui_main
    return gui_main()


if __name__ == "__main__":
    raise SystemExit(main())
