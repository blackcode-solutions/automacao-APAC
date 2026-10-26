"""Entry PyInstaller: sem args → UI; com args → CLI."""

from __future__ import annotations

import sys


def main() -> int:
    # PyInstaller passa só o path do exe em argv[0].
    if len(sys.argv) <= 1:
        from apac_bot.ui.app import run_ui

        run_ui(None)
        return 0
    from apac_bot.cli import main as cli_main

    return int(cli_main() or 0)


if __name__ == "__main__":
    raise SystemExit(main())
