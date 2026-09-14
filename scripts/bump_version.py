#!/usr/bin/env python3
"""Update the canonical ClayFarm control-plane version in one file."""
from __future__ import annotations

import re
import sys
from pathlib import Path

VERSION = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+(?:[.-][0-9A-Za-z.-]+)?$")


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 1 or not VERSION.fullmatch(args[0]):
        print("usage: bump_version.py MAJOR.MINOR.PATCH[-prerelease]", file=sys.stderr)
        return 2
    path = Path(__file__).resolve().parents[1] / "src/clayfarm_control/version.py"
    text = path.read_text(encoding="utf-8")
    updated, count = re.subn(r'(__version__\s*=\s*)"[^"]+"', rf'\g<1>"{args[0]}"', text, count=1)
    if count != 1:
        print("canonical version assignment not found", file=sys.stderr)
        return 2
    path.write_text(updated, encoding="utf-8")
    print(args[0])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
