"""Load the exported game data (web/public/data) for the Python reference simulator."""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "web" / "public" / "data"


@dataclass
class Playbook:
    n: int
    cols: dict[str, list[int]]
    index: dict[str, dict[str, list[int]]]
    codebooks: dict[str, list[str]]

    def cell(self, family: str, call: str, look: str, zone: str, min_n: int) -> tuple[int, int, str]:
        """Most specific cell with >= min_n rows: (start, len, level). Backoff L3 -> L0."""
        for level, key in (("L3", f"{family}|{call}|{look}|{zone}"), ("L2", f"{family}|{call}|{look}"),
                           ("L1", f"{family}|{call}"), ("L0", family)):
            c = self.index[level].get(key)
            if c is not None and c[1] >= min_n:
                return c[0], c[1], level
        c = self.index["L0"].get(family)
        if c is None:
            raise KeyError(f"no rows for family {family}")
        return c[0], c[1], "L0"

    def row(self, i: int) -> dict[str, int]:
        return {k: v[i] for k, v in self.cols.items()}


@dataclass
class EngineData:
    cfg: dict
    wp: dict
    fg: dict
    pat: dict
    kickoff: dict
    punt: dict
    clock: dict
    looks: dict
    tendencies: dict
    playbook: Playbook


@lru_cache(maxsize=1)
def load(data_dir: Path | None = None) -> EngineData:
    d = data_dir or DATA_DIR
    eng = json.loads((d / "engine_data.json").read_text())
    pb = json.loads((d / "playbook.json").read_text())
    playbook = Playbook(n=pb["n"], cols=pb["columns"], index=pb["index"], codebooks=pb["codebooks"])
    return EngineData(cfg=eng["config"], wp=eng["wp"], fg=eng["fg"], pat=eng["pat"], kickoff=eng["kickoff"],
                      punt=eng["punt"], clock=eng["clock"], looks=eng["looks"], tendencies=eng["tendencies"],
                      playbook=playbook)


@lru_cache(maxsize=1)
def load_game(data_dir: Path | None = None) -> dict:
    d = data_dir or DATA_DIR
    return json.loads((d / "game.json").read_text())
