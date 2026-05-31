"""Minimal CLI entry point — delegates to browser-harness.

Usage::

    BU_CDP_URL=http://127.0.0.1:9223 cdp-capture < script.py

The library is designed to run **inside** the browser-harness runtime
(``browser-harness < your_script.py``).  This CLI wrapper simulates that
behaviour for convenience, but the recommended pattern is to pipe your
script to ``browser-harness`` directly.
"""

from __future__ import annotations

import sys


def main() -> None:
    """Read Python code from stdin and exec in browser-harness context.

    This mimics what ``browser-harness < script.py`` does, but with
    ``cdp_capture`` pre-imported.
    """
    code = sys.stdin.read()
    if not code.strip():
        print("Usage: BU_CDP_URL=http://127.0.0.1:9223 cdp-capture < script.py", file=sys.stderr)
        sys.exit(1)

    # The cdp_capture package is already importable; inject it so
    # user scripts can do ``from cdp_capture import run`` without
    # worrying about sys.path.
    import cdp_capture  # noqa: F401

    exec(code, {"cdp_capture": cdp_capture})


if __name__ == "__main__":
    main()
