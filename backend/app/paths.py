from __future__ import annotations

from pathlib import Path

# backend/ (sibling of app/)
BACKEND_ROOT = Path(__file__).resolve().parents[1]

# HTML snapshots live beside app/, not under it — keeps uvicorn --reload-dir app stable.
SNAPSHOT_ROOT = BACKEND_ROOT / "data" / "snapshots"
