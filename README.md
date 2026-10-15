# Final Drive

An original daily NFL play-calling game. Each day you call the plays on one real late-game
drive, and a Monte Carlo simulator grades every call against what NFL play-callers would do.

Not affiliated with the NFL or its teams. All data comes from the public
[nflverse](https://github.com/nflverse) project (CC-BY-4.0). No logos or official marks are used.

## Layout

```
pipeline/      Python: ingest -> spots -> playbook -> ratings -> wp_model -> coaches -> export
sim/           Python reference simulator + tests
engine/        TypeScript port of the simulator, runs in Web Workers
web/           Vite + TypeScript front end (public/data holds exported game data)
api/           Cloudflare Worker: /board, /daily
config/        tuning.json: every tunable number (speeds, thresholds, sim counts) in one place
scripts/       build.py: stamps build hash, packs + gzips data
data/raw       nflverse parquet cache (gitignored)
data/processed pipeline outputs and reports (gitignored)
```

## Setup

```
uv sync && pnpm install                    # Python 3.12 env + Node toolchain

# data pipeline (about 2 minutes end to end; ~155 MB of nflverse parquet cached in data/raw)
uv run python pipeline/ingest.py pull      # 2016-2026 pbp, participation, rosters, schedules, FTN, players
uv run python pipeline/ingest.py report    # per-season field completeness
uv run python pipeline/playbook.py build   # play library: calls x looks x outcomes + bucket report
uv run python pipeline/spots.py build      # late-game spots (2023+) with the real drive and result
uv run python pipeline/wp_model.py         # WP, FG, PAT, kickoff, punt, clock, tendencies -> models.json
uv run python pipeline/coaches.py          # coach tendency profiles
uv run python pipeline/ratings.py          # player ratings 40-99
uv run python pipeline/export.py           # web/public/data/{engine_data,playbook,game}.json + spots/
uv run python scripts/build.py             # pack playbook.bin / hints.bin (gzip typed arrays)

# checks
uv run pytest                              # pipeline + simulator tests (clock, scoring, kickoffs, OT)
uv run python sim/validate.py              # sim win rates vs real outcomes  -> docs/phase2_validation.md
uv run python sim/validate_grading.py      # grade stability + percentile spread -> docs/phase3_grading.md
uv run python sim/parity_dump.py && npm run parity   # TS engine == Python engine on 1,200 seeded games
npm test                                   # vitest engine tests

# app
npm run dev                                # http://127.0.0.1:5173
npm run build                              # web/dist (static); see api/README.md for the Worker
```

Every judgment call made while building is logged in `decisions.md`.

Generated reports are copied into `docs/` (the `data/` tree is gitignored).

## Roadmap

See `PLAN.md`. Work proceeds one phase at a time; each phase ends with its exit criteria checked.
