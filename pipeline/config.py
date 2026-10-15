"""Load the single tuning config shared by the Python pipeline, the reference
simulator, and (via direct JSON import) the TypeScript engine."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config" / "tuning.json"
DATA_DIR = ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
PROCESSED_DIR = DATA_DIR / "processed"


@lru_cache(maxsize=1)
def load_config() -> dict[str, Any]:
    with CONFIG_PATH.open() as f:
        return json.load(f)


def cfg(*keys: str) -> Any:
    """cfg("grading", "round1_sims") -> 600"""
    node: Any = load_config()
    for k in keys:
        node = node[k]
    return node


def ingest_seasons() -> list[int]:
    return list(range(cfg("seasons", "ingest_first"), cfg("seasons", "ingest_last") + 1))
