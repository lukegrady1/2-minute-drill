import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from pipeline.normalize import (
    blitz_flag,
    box_bucket,
    depth_bucket,
    look_label,
    normalize_formation,
    parse_personnel,
)


def test_ngs_personnel():
    p = parse_personnel("1 RB, 1 TE, 3 WR")
    assert (p.rb, p.te, p.wr, p.ol) == (1, 1, 3, 5)
    assert p.group == "11" and p.klass == "11"
    j = parse_personnel("6 OL, 1 RB, 2 TE, 1 WR")
    assert j.ol == 6 and j.klass == "jumbo"
    e = parse_personnel("0 RB, 0 TE, 5 WR")
    assert e.klass == "10"


def test_ftn_personnel():
    p = parse_personnel("1 C, 2 G, 1 QB, 1 RB, 2 T, 1 TE, 3 WR")
    assert (p.rb, p.te, p.wr, p.ol, p.qb) == (1, 1, 3, 5, 1)
    assert p.klass == "11"
    fb = parse_personnel("1 C, 1 FB, 2 G, 1 QB, 1 RB, 2 T, 1 TE, 2 WR")
    assert fb.rb == 2 and fb.fb == 1 and fb.klass == "21"
    jumbo = parse_personnel("1 C, 1 G, 1 QB, 1 RB, 3 T, 1 TE, 3 WR")
    assert jumbo.ol == 5 and jumbo.klass == "11"  # 1+1+3 = 5 OL, a tackle-eligible swap
    jumbo2 = parse_personnel("1 C, 2 G, 1 QB, 1 RB, 3 T, 2 TE, 1 WR")
    assert jumbo2.ol == 6 and jumbo2.klass == "jumbo"


def test_personnel_garbage():
    assert parse_personnel(None) is None
    assert parse_personnel("") is None
    assert parse_personnel("1 FS, 2 LB, 1 K") is None  # kick team charted as offense


def test_formation_ngs_passthrough():
    p = parse_personnel("1 RB, 1 TE, 3 WR")
    for f in ("SHOTGUN", "SINGLEBACK", "I_FORM", "PISTOL", "JUMBO", "WILDCAT"):
        assert normalize_formation(f, p) == f
    assert normalize_formation("EMPTY", p) == "EMPTY"


def test_formation_ftn_derivation():
    eleven = parse_personnel("1 C, 2 G, 1 QB, 1 RB, 2 T, 1 TE, 3 WR")
    assert normalize_formation("UNDER CENTER", eleven) == "SINGLEBACK"
    fb = parse_personnel("1 C, 1 FB, 2 G, 1 QB, 1 RB, 2 T, 1 TE, 2 WR")
    assert normalize_formation("UNDER CENTER", fb) == "I_FORM"
    six_ol = parse_personnel("1 C, 2 G, 1 QB, 1 RB, 3 T, 2 TE, 1 WR")
    assert normalize_formation("UNDER CENTER", six_ol) == "JUMBO"
    empty = parse_personnel("1 C, 2 G, 1 QB, 0 RB, 2 T, 1 TE, 4 WR")
    assert normalize_formation("SHOTGUN", empty) == "EMPTY"
    assert normalize_formation(None, eleven, qb_location="S") == "SHOTGUN"
    assert normalize_formation(None, None, qb_location="U") == "SINGLEBACK"
    assert normalize_formation(None, None) is None


def test_depth_and_look():
    assert depth_bucket(-3) == "short"
    assert depth_bucket(9) == "short"
    assert depth_bucket(10) == "medium"
    assert depth_bucket(19) == "medium"
    assert depth_bucket(20) == "deep"
    assert depth_bucket(None) is None
    assert box_bucket(6) == "light" and box_bucket(7) == "heavy"
    assert blitz_flag(4) is False and blitz_flag(5) is True and blitz_flag(0) is None
    assert look_label("light", None) == "light_any"
    assert look_label("heavy", True) == "heavy_blitz"
    assert look_label(None, True) is None
