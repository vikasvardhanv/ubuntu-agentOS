#!/usr/bin/env python3
"""Create the simple SysV ar archive format required by Debian packages."""

from __future__ import annotations

import os
import sys
from pathlib import Path


def member(path: Path) -> bytes:
    data = path.read_bytes()
    name = path.name.encode()
    if len(name) > 16:
        raise ValueError(f"ar member name too long: {path.name}")
    stat = path.stat()
    header = (
        name.ljust(16)
        + str(int(stat.st_mtime)).encode().ljust(12)
        + str(stat.st_uid).encode().ljust(6)
        + str(stat.st_gid).encode().ljust(6)
        + oct(stat.st_mode & 0o7777)[2:].encode().ljust(8)
        + str(len(data)).encode().ljust(10)
        + b"`\n"
    )
    return header + data + (b"\n" if len(data) % 2 else b"")


def main() -> None:
    output = Path(sys.argv[1])
    output.write_bytes(b"!<arch>\n" + b"".join(member(Path(value)) for value in sys.argv[2:]))
    os.chmod(output, 0o644)


if __name__ == "__main__":
    main()
