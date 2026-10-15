import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from pipeline.config import RAW_DIR, cfg, load_config
from pipeline.ingest import parse_seasons, raw_path


def test_parse_seasons_range_and_list():
    assert parse_seasons("2016-2018") == [2016, 2017, 2018]
    assert parse_seasons("2024,2022,2024") == [2022, 2024]
    assert parse_seasons("2016-2017,2020") == [2016, 2017, 2020]


def test_parse_seasons_defaults_to_config():
    s = parse_seasons(None)
    assert s[0] == cfg("seasons", "ingest_first")
    assert s[-1] == cfg("seasons", "ingest_last")


def test_raw_path_layout():
    assert raw_path("pbp", 2023) == RAW_DIR / "pbp" / "pbp_2023.parquet"
    assert raw_path("players", None) == RAW_DIR / "players" / "players.parquet"


def test_config_has_plan_numbers():
    c = load_config()
    assert c["grading"]["round1_sims"] == 600
    assert c["grading"]["round2_sims"] == 3000
    assert c["playbook"]["min_bucket_size"] == 30
    assert c["rules"]["kickoff_touchback_yardline"] == 35
    assert set(c["motion"]["positions"]) >= {"WR", "QB", "OL", "DT"}
