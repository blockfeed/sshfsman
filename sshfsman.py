#!/usr/bin/env python3
"""Repo-run wrapper for sshfsman.

When installed (pipx/pip), use:  sshfsman ...
When running from a git checkout, use: ./sshfsman.py ...

This wrapper ensures ./src is on sys.path and dispatches to sshfsman.cli.
"""

from __future__ import annotations

import sys
from pathlib import Path


def main() -> int:
    repo_root = Path(__file__).resolve().parent
    src = repo_root / "src"
    if src.is_dir():
        sys.path.insert(0, str(src))
    from sshfsman.cli import main as real_main  # noqa: WPS433

    return int(real_main())


if __name__ == "__main__":
    raise SystemExit(main())
