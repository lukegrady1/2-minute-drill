"""Pack web/public/data for shipping: playbook.json -> playbook.bin (gzip, typed arrays),
stamp the build hash into web/public/data/build.json.

    uv run python scripts/build.py
"""

from __future__ import annotations

import gzip
import json
import struct
import subprocess
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "web" / "public" / "data"

ENGINE_COLS = {  # column -> dtype
    "yards": "i2", "to": "i1", "def_td": "i1", "nullified": "i1", "pen": "i1", "pen_yds": "i2",
    "inc": "i1", "sack": "i1", "oob": "i1", "td": "i1", "air": "i2", "ret": "i2", "safety": "i1",
}
HINT_COLS = {
    "yac": "i2", "ttt10": "i2", "tgt": "i1", "route": "i1", "press": "i1", "cov": "i1", "pers": "i1",
    "form": "i1", "comp": "i1", "scr": "i1", "fd": "i1", "season": "i2", "yl": "i1",
}


def pack(columns: dict[str, list[int]], spec: dict[str, str]) -> tuple[dict, bytes]:
    header = {"columns": [], "n": None}
    blobs = []
    offset = 0
    for name, dt in spec.items():
        arr = np.asarray(columns[name], dtype=np.dtype("<" + dt))
        b = arr.tobytes()
        header["columns"].append({"name": name, "dtype": dt, "offset": offset, "length": len(arr)})
        header["n"] = len(arr)
        blobs.append(b)
        offset += len(b)
    return header, b"".join(blobs)


def write_bin(path: Path, header: dict, body: bytes) -> int:
    h = json.dumps(header, separators=(",", ":")).encode()
    raw = struct.pack("<I", len(h)) + h + body
    gz = gzip.compress(raw, compresslevel=9, mtime=0)
    path.write_bytes(gz)
    return len(gz)


def main() -> int:
    pb = json.loads((DATA / "playbook.json").read_text())
    cols = pb["columns"]
    hdr, body = pack(cols, ENGINE_COLS)
    hdr["index"] = pb["index"]
    hdr["codebooks"] = pb["codebooks"]
    n = write_bin(DATA / "playbook.bin", hdr, body)
    hh, hbody = pack(cols, HINT_COLS)
    nh = write_bin(DATA / "hints.bin", hh, hbody)
    sha = "dev"
    try:
        sha = subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, text=True).strip()
    except Exception:  # noqa: BLE001
        pass
    (DATA / "build.json").write_text(json.dumps({"build": sha}))
    for f in ("engine_data.json", "game.json"):
        gz = gzip.compress((DATA / f).read_bytes(), compresslevel=9, mtime=0)
        print(f"{f}: {(DATA / f).stat().st_size / 1e6:.2f} MB raw, {len(gz) / 1e6:.2f} MB gzip (served by the host)")
    print(f"playbook.bin: {len(body) / 1e6:.2f} MB raw -> {n / 1e6:.2f} MB gzip; hints.bin: {len(hbody) / 1e6:.2f} MB raw -> {nh / 1e6:.2f} MB gzip; build {sha}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
