# nflverse data notes (Phase 1 findings, 2026-10-15)

Produced by `uv run python pipeline/ingest.py report`; full table in `data/processed/field_coverage.md`.

## Completeness (share of run/pass scrimmage plays; air_yards is share of thrown passes)

| field | 2016-2022 | 2023-2025 | 2026 |
|---|---|---|---|
| offense_personnel | 100% | 100% | none (participation not published in-season) |
| offense_formation | 99.0-99.9% | 99.7-99.9% | none |
| air_yards (pbp) | 99.4-99.6% | 99.4-99.6% | 99.4% |
| 22 player ids | 100% | 100% | none |
| defenders_in_box | 99.9% | 100% | none in participation; FTN `n_defense_box` 100% |
| number_of_pass_rushers | ~60% (pass plays only) | 98-100% (0 on runs) | FTN `n_pass_rushers` 100% |
| coverage / man-zone | 0% 2016-17, ~55% 2018-22 | ~60% | none |
| was_pressure, time_to_throw, route | ~53-56% (pass plays only) | same (pressure 100%: False on runs) | none |

## Two different participation providers

* **2016-2022** (NGS-derived, 20 columns). Formation vocabulary: SHOTGUN, SINGLEBACK, I_FORM,
  EMPTY, PISTOL, JUMBO, WILDCAT. Personnel is skill-only: `1 RB, 1 TE, 3 WR`.
  Defense personnel: `4 DL, 2 LB, 5 DB`.
* **2023-2025** (FTN-derived, 26 columns, adds names/positions/numbers). Formation vocabulary is
  only SHOTGUN, UNDER CENTER, PISTOL. Personnel lists every position including OL and QB:
  `1 C, 2 G, 1 QB, 1 RB, 2 T, 1 TE, 3 WR`. Defense personnel is per-position too.

Consequence for `playbook.py`: write one normalizer that maps both formats to the plan's
personnel groups (11, 12, 21, 13, 22, 10/empty, jumbo) and to one formation set. For 2023+,
derive EMPTY from 0 RB, JUMBO from 6+ OL (C+G+T), and I_FORM / SINGLEBACK from FB presence
under center; the plan's 7-formation list is only directly observed for 2016-2022.

## 2026 (current season)

nflverse publishes participation a season in arrears, so 2026 has none. FTN charting does
cover 2026 (box count, pass rushers, blitzers, play action, RPO, screen, motion, no-huddle,
QB location S/U/P, QB sneak), so 2026 plays can still be bucketed by look and call type; only
the on-field 22 and formation need a fallback (weekly rosters + depth charts + formation templates).

## Other
* pbp carries no formation/personnel columns of its own; everything comes from the join on
  (`game_id`, `play_id`) to participation (`nflverse_game_id`) and FTN (`nflverse_play_id`).
* FTN joins to 99.7-100% of scrimmage plays for 2022-2026.
* Raw cache: ~155 MB of zstd parquet under `data/raw/` (gitignored); manifest at `data/raw/manifest.json`.
