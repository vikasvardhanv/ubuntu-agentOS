from __future__ import annotations

import os
import sqlite3
from pathlib import Path


def main() -> None:
    state_dir = Path(os.getenv("AGENTOS_STATE_DIR", "./var"))
    state_dir.mkdir(parents=True, exist_ok=True)
    schema = Path("db/migrations/001_initial.sql").read_text(encoding="utf-8")
    with sqlite3.connect(state_dir / "agentos.db") as connection:
        connection.executescript(schema)
    print(state_dir / "agentos.db")


if __name__ == "__main__":
    main()
