"""Normalize nflverse fields across the two participation providers.

2016-2022 (NGS):  personnel "1 RB, 1 TE, 3 WR" (OL only listed when != 5),
                  formation in {SHOTGUN, SINGLEBACK, I_FORM, EMPTY, PISTOL, JUMBO, WILDCAT}
2023+     (FTN):  personnel "1 C, 2 G, 1 QB, 1 RB, 2 T, 1 TE, 3 WR" (every position),
                  formation in {SHOTGUN, UNDER CENTER, PISTOL}

Everything here is pure functions on strings/numbers so it is easy to test and to port.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from pipeline.config import cfg

_TOKEN = re.compile(r"(\d+)\s*([A-Za-z]+)")

RB_LIKE = {"RB", "FB", "HB"}
OL_LIKE = {"OL", "C", "G", "T", "OT", "OG"}

FORMATIONS = ("SHOTGUN", "SINGLEBACK", "I_FORM", "EMPTY", "PISTOL", "JUMBO", "WILDCAT")
PERSONNEL_CLASSES = ("11", "12", "21", "13", "22", "10", "jumbo", "other")


@dataclass(frozen=True)
class Personnel:
    rb: int
    te: int
    wr: int
    ol: int
    qb: int
    fb: int

    @property
    def group(self) -> str:
        """Two-digit nflverse-style code: RBs then TEs (e.g. '11', '12', '21')."""
        return f"{self.rb}{self.te}"

    @property
    def klass(self) -> str:
        """Coarse class used by the playbook backoff and the UI chips."""
        if self.ol >= 6 or (self.rb + self.te) >= 4:
            return "jumbo"
        g = self.group
        if g in ("11", "12", "21", "13", "22"):
            return g
        if self.te == 0 and self.rb <= 1:
            return "10"
        return "other"


def parse_personnel(s: str | None) -> Personnel | None:
    """Parse either provider's personnel string. Returns None for empty/unparseable."""
    if not s or not isinstance(s, str):
        return None
    counts: dict[str, int] = {}
    for n, pos in _TOKEN.findall(s):
        counts[pos.upper()] = counts.get(pos.upper(), 0) + int(n)
    if not counts:
        return None
    rb = sum(v for k, v in counts.items() if k in RB_LIKE)
    fb = counts.get("FB", 0)
    te = counts.get("TE", 0)
    wr = counts.get("WR", 0)
    ol_listed = sum(v for k, v in counts.items() if k in OL_LIKE)
    qb = counts.get("QB", 1) if "QB" in counts else 1
    # NGS strings omit the 5 OL unless the count differs from 5.
    ol = ol_listed if ol_listed else 5
    # Rows that are clearly not an offensive grouping (e.g. kick teams charted as offense).
    if rb + te + wr == 0:
        return None
    return Personnel(rb=rb, te=te, wr=wr, ol=ol, qb=qb, fb=fb)


def normalize_formation(
    raw: str | None, personnel: Personnel | None, qb_location: str | None = None
) -> str | None:
    """Map both providers (and FTN qb_location as a last resort) onto FORMATIONS."""
    f = (raw or "").strip().upper()
    if not f and qb_location:
        f = {"S": "SHOTGUN", "U": "UNDER CENTER", "P": "PISTOL"}.get(qb_location.strip().upper(), "")
    if not f:
        return None
    if f in FORMATIONS:
        if f == "SHOTGUN" and personnel and personnel.rb == 0:
            return "EMPTY"
        return f
    if f == "UNDER CENTER":
        if personnel is None:
            return "SINGLEBACK"
        if personnel.ol >= 6:
            return "JUMBO"
        if personnel.fb >= 1 or personnel.rb >= 2:
            return "I_FORM"
        return "SINGLEBACK"
    return None


def depth_bucket(air_yards: float | None) -> str | None:
    if air_yards is None:
        return None
    d = cfg("playbook", "depth_buckets")
    if air_yards <= d["short_max_air_yards"]:
        return "short"
    if air_yards <= d["medium_max_air_yards"]:
        return "medium"
    return "deep"


def box_bucket(defenders_in_box: int | None) -> str | None:
    if defenders_in_box is None:
        return None
    return "light" if defenders_in_box <= cfg("playbook", "light_box_max") else "heavy"


def blitz_flag(pass_rushers: int | None) -> bool | None:
    if pass_rushers is None or pass_rushers <= 0:
        return None
    return pass_rushers >= cfg("playbook", "blitz_min_rushers")


def look_label(box: str | None, blitz: bool | None) -> str | None:
    """'light_base', 'heavy_blitz', or 'light_any' when blitz is unknown (run plays)."""
    if box is None:
        return None
    if blitz is None:
        return f"{box}_any"
    return f"{box}_{'blitz' if blitz else 'base'}"
