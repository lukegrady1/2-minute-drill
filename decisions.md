# Decisions log

Every judgment call made while building, in order. Each entry has the decision, the
alternatives, and where it lives in code. Mark each one **keep / change / revisit** when you review.

Status key: `[ ]` not yet reviewed.

---

## Phase 1: data foundation

### D1. Working name is "Final Drive"
`[ ]` The brief left the name as a placeholder. PLAN.md suggests Clutch Call, Final Drive, 4th & Gold,
and its repo layout uses `final-drive/`. Chosen: **Final Drive**, as one string in `config/tuning.json`
(`game.name`) and the README. Nothing else depends on it. Domain and USPTO not checked.

### D2. Python toolchain is uv + Python 3.12, polars instead of pandas for the pipeline
`[ ]` System Python is 3.9. uv was already installed, so the project pins 3.12 via `.python-version`.
nflreadpy returns polars frames, so the pipeline stays in polars; pandas is installed for modelling only.

### D3. One tunables file, `config/tuning.json`, shared by Python and TypeScript
`[ ]` JSON rather than TOML/YAML so the TS engine imports it with no parser. Every number from PLAN.md
(sim counts, thresholds, speeds, clock rules, kickoff rules, OT rules) is in it. Alternative was a
Python module plus a generated TS file; rejected because two copies drift.

### D4. Ingest also pulls FTN charting and the players table by default
`[ ]` The brief listed pbp, participation, rosters, schedules. PLAN.md's ingest step also lists FTN
(play action, RPO, screens, blitz) and players. Both are small and FTN is required for RPO/PA calls,
so they are in the default set. Depth charts and injuries are available via `--datasets` but not default.

### D5. Missing seasons are "unavailable", not failures
`[ ]` nflreadpy raises ValueError for participation 2026 (published a season in arrears). The manifest
records it as `unavailable` and the run exits 0. A real download error still exits with the error listed.

### D6. Participation normalizer derives formations for 2023+
`[ ]` The provider changed in 2023: NGS (7 formations, skill-only personnel) to FTN (Shotgun / Under
Center / Pistol, personnel lists every position). `pipeline/normalize.py` maps both to one vocabulary:
UNDER CENTER becomes JUMBO when OL >= 6, I_FORM when a FB is listed or RB >= 2, else SINGLEBACK;
SHOTGUN with 0 RB becomes EMPTY. So 2023+ "Empty" only catches true 0-RB sets, and "Singleback" vs
"I-form" is inferred. Alternative: keep two vocabularies and only offer 3 formations. Rejected because
the UI wants one chip set.

### D7. Personnel classes: 11, 12, 21, 13, 22, 10, jumbo, other
`[ ]` jumbo = 6+ OL or RB+TE >= 4. "10" = 0-1 RB and 0 TE. Anything else (e.g. 20, 02, 31) is "other".

### D8. Run calls are bucketed by box only; blitz applies to pass calls only
`[ ]` Pass rushers are never charted on run plays (null 2016-22, zero 2023+), so a run row's look is
`light_any` / `heavy_any`. When the defense picks (box, blitz), a run samples by box and ignores blitz.
Alternatives: drop blitz entirely (loses the pass-rush dimension), or treat FTN `n_blitzers` as a run
blitz (it is also 0 on runs). Revisit if a run-blitz signal appears.

### D9. Run direction is left / middle / right; inside vs outside from the gap
`[ ]` inside = location middle or gap guard; outside = gap tackle/end and not middle. PLAN.md says
"strong/weak side", but strength needs alignment data we don't have, so direction is left/right/middle.
"middle" runs are always inside. ~1% of runs have no location; they get a seeded draw.

### D10. Sacks, scrambles, throwaways and nullified dropbacks get a drawn depth and direction
`[ ]` They have no air yards but must live inside pass calls (so a "deep pass" call can end in a sack).
Depth is drawn with the pipeline seed from P(depth | down) x pressure rate(depth), where pressure rate
comes from participation `was_pressure`. Direction is drawn from P(direction | depth). 19.5% of
dropbacks are affected. Alternative: a separate "dropback" pool mixed in at a fixed rate. Rejected as
harder to port. RPO and screen rows keep depth null when not thrown.

### D11. QB sneak before 2022 = designed QB run with <= 2 to go
`[ ]` FTN flags sneaks from 2022. Before that, the rule is rusher position QB, not a scramble, ydstogo
<= 2. This yields 63-200 per season vs ~330 with FTN, so pre-2022 sneaks are under-counted.

### D12. Hail Mary = thrown >= 30 air yards, into or near the end zone, <= 15 s left in the half
`[ ]` Only ~200 plays in 11 seasons. It is the one call whose look cells fall below 30; the sampler will
back off to the family level for it. Also excluded from "better call" suggestions along with gadget plays.

### D13. Scrambles are outcomes of pass calls, not a call
`[ ]` PLAN.md lists "QB scramble" as a call example. nflfastR tags scrambles as runs with
`qb_scramble=1`; they are really dropbacks that broke down, so they live inside pass-call buckets.
The player cannot call a scramble.

### D14. Playbook rows keep every season 2016-2026; nothing is restricted to 2023+
`[ ]` Both the full-season grid and the 2023+ grid pass the 30-play criterion, so the simulator can
prefer recent seasons later via weighting rather than filtering.

### D15. Clock runoff = seconds from this snap to the next snap in the same half
`[ ]` Stored per row as `runoff_s` plus `timeout_after`. This includes huddle time when the clock ran.
The simulator will split it into play duration (from stopped-clock plays) and tempo (clock model).

### D16. Spots: one per possession, starting at the first qualifying snap
`[ ]` A drive that started at 3:00 and crosses 2:30 becomes a spot at its first snap inside 2:30
(e.g. 2nd and 7). Both teams' drives qualify. Kneel-first drives are flagged `kneel_start` and left
out of the pool. Pool: 3,133 spots (2023-2026) vs the 700 target.

### D17. Q2 spots have no margin or field-position filter yet
`[ ]` PLAN.md's rule is just "Q2 with <= 2:00 left", so 2,269 "tight" spots are mostly end-of-half and
many are low stakes (down 3 scores, own 20, 0:30 left). Suggest adding a filter (e.g. one-score or
within 50 yards with >= 0:40) before building the daily schedule. Not applied.

### D18. Spot categories: Q2 is always "tight"
`[ ]` drill = Q4 trailing with the ball, protect = Q4 leading, tight = Q4 tied or any Q2 spot.
Matches PLAN.md's three tiles.

### D19. 2026 plays use FTN for box, rushers and formation; personnel is unknown
`[ ]` Participation is missing for the current season. FTN `n_defense_box` / `n_pass_rushers` give
the look and `qb_location` gives a coarse formation, so 2026 rows are fully usable in call x look
cells. Personnel backoff will skip the personnel level for them.

### D20. Reports live in `docs/` as copies; `data/` is gitignored
`[ ]` PLAN.md asked for "a notebook" showing bucket counts. The reports are generated Markdown
(`docs/phase1_*.md`) rather than a Jupyter notebook, so they diff in git.

## Phase 2: models and simulator

### D21. WP model is a logistic regression on 21 engineered features, exported as coefficients
`[ ]` PLAN.md allowed a GBM + lookup grid. A grid over score x time x field x down x distance x
timeouts is millions of cells; a coefficient vector is 21 numbers and both engines evaluate it the
same way. Fit on 417k plays 2016-2026: log loss 0.444, MAE 0.021 vs nflverse `vegas_wp`,
calibration within 1 point per decile. It is only used to value halftime (Q2 spots) and for
instant WP displays; Q4 sims play to the end. `pipeline/wp_model.py`, `sim/models.py`.

### D22. FG model: logistic on distance, distance^2, indoor, wind, temp, distance x wind, max(d-52, 0)
`[ ]` The hinge at 52 yards is PLAN.md's "taper past 52". Model vs actual by 5-yard bin: 50: .697/.708,
55: .591/.611, 60: .473/.419 (n=86). Attempts over 68 yards are refused. Kicker skill is not in yet
(ratings phase). Blocked kicks count as misses.

### D23. Kickoff table from 2025-2026 only (touchback at the 35)
`[ ]` 2024 used the 30-yard touchback, so it is excluded. 3,634 kickoffs: mean start yardline_100
69.7, return TD 0.2%, onside recovery 7.8% (n=64). Kickoff return in the sim is a histogram draw of
the receiving team's start spot; touchback (yl=65) leaves the clock stopped, a return starts it.

### D24. Punt table: receiving-team start spot histogram by 7 punting zones, 2016-2026
`[ ]` Blocks and return TDs are per-zone rates. Rare "touchback vs downed" detail is implicit in the
histogram. A blocked punt gives the ball at the line of scrimmage.

### D25. Clock model: play duration by type (from stopped-clock plays) + tempo distributions
`[ ]` Duration: run 7.6 s, completed pass 7.4 s, incomplete 5.1 s. Tempo (pre-snap seconds when the
clock runs, after subtracting a 6 s typical duration): hurry 24 s, normal 32 s, milk 29 s.
Milk < normal is suspicious (two-minute-warning and end-of-quarter truncation were removed, but
defensive timeouts may still bias it). The sim uses the data as is; kneels always bleed the full
40 s play clock (rule, not data). Spikes snap within 3 s. Revisit milk.

### D26. Penalties are outcomes carried by sampled rows; no separate penalty model, no decline logic
`[ ]` A nullified row applies its penalty yards (half-the-distance capped) and replays the down;
defensive penalties of 10+ yards give an automatic first down; a penalty tacked onto a standing play
is added after the gain. PLAN.md wanted accept/decline via WP; every sampled penalty is treated as
accepted, which matches the data (declined penalties leave no `penalty_yards`).

### D27. Interception spot = line of scrimmage minus air yards; fumbles at the end of the run
`[ ]` Then the return yards from the row. A row flagged `return_touchdown` is a defensive score.

### D28. Two-minute warning: clock snaps to 2:00 when runoff crosses it, taken once per half
`[ ]` Pre-snap runoff that crosses 2:00 stops at 2:00 with no play run; a play that ends past 2:00
stops the clock there. Out-of-bounds stops the clock only inside 2:00 (Q2) / 5:00 (Q4) per config;
outside that window the clock restarts on the ready signal, modelled as "running" before the next snap.

### D29. Overtime (2025 rules) in the engine
`[ ]` 10:00 regular season / 15:00 playoffs, 2/3 timeouts, seeded coin toss (winner receives). Both
teams possess once even after an opening TD; after both have possessed, next score wins. Regular
season ties stand when the period expires; playoffs add periods. A possession "ends" on any change
of possession or score. A defensive TD on the first possession ends the game (both teams have
effectively had the ball). `sim/engine.py`, `sim/tests/test_overtime.py`.

### D30. Auto-policy = league tendencies with hierarchical backoff + end-game rules
`[ ]` Tendencies: P(call | half, clock bucket, score state, down, distance, zone) from 157k late
plays, 5 backoff levels, min 20 rows. Rules on top (in `sim/policy.py`): kneel when the lead can be
run out (42 s per kneel, opponent timeouts stop it); spike with no timeouts and <= 25 s; must-kick FG
on 4th down trailing by <= 3 inside 2:00; no punting when trailing late; Hail Mary only <= 20 s from
30+ yards out; 2-pt chart {-2, -5, -10, -13, -16, +1, +4} inside 5:00; onside when trailing in Q4
with clock <= 60 + 45 x timeouts. Defense look sampled from P(light box), P(blitz) by down x distance.

### D31. Timeout policy (v1) is crude: trailing or tied inside 2:00 with the clock running = call it
`[ ]` Plus the trailing defense inside 3:00. This burns timeouts early (see the smoke run). It affects
grading because the auto-policy is the benchmark. Candidate for a data-driven model from
`timeout_after` rows. Revisit.

### D32. QB sneak is offered only on <= 2 to go (or inside the 2)
`[ ]` Hail Mary only from 30+ yards out. Both are in `Engine.legal_actions`.

### D33. The Python sim reads the same exported JSON the browser will load
`[ ]` `web/public/data/{engine_data,playbook,game}.json`. Guarantees parity with the TS engine.
playbook.json is 24 MB uncompressed for now; Phase 4 packs it as gzipped typed arrays.

### D34. Late-game plays are not weighted or filtered in the play library
`[ ]` Checked: late trailing passes gain slightly *less* than the all-season average (short 4.5 vs
4.7 yds, deep 7.6 vs 9.7) with more interceptions. So preferring late rows would not make the
trailing offense more realistic; cells stay all-situation (field zone is the only situational key).

### D35. Hurry tempo is fit from real two-minute drills only
`[ ]` First version pooled all no-huddle plays (median 31 s between snaps). Trailing/tied offenses
inside Q4 2:30 / Q2 2:00 with the clock running snap every 20 s (median), i.e. ~14 s pre-snap.
This was the main reason simulated trailing offenses lost too often.

### D36. Timeout usage is a data table, not a rule
`[ ]` P(timeout after a running-clock play | half, caller = trailing offense or trailing defense,
clock bucket, caller's timeouts left), from Q4 <= 4:00 and Q2 <= 2:00. Examples: trailing offense with
timeouts, 31-60 s left: 35-42%; 2:01-3:00: 3%; trailing defense 1:01-2:00: 51%. The leading side never
stops the clock; a tied game gives the decision to the offense. Replaces D31.

### D37. Play durations come from incompletions and in-window out-of-bounds plays only
`[ ]` First fit pooled every "clock stops" play, which included out-of-bounds plays outside the
stopping window where the gap to the next snap contains the restart. Result: run 6.4 s, completed
pass 5.9 s, incompletion 5.1 s. Tempo fits drop gaps under 8 s (impossible with a running clock),
which lifted milk to 36 s pre-snap (was 29).

### D38. End-game field-goal management rules in the auto-policy
`[ ]` When a FG wins or ties (trailing by <= 3 or tied) and the offense is in range with <= 40 s: call
timeout if the clock runs and one is left, else spike on downs 1-3, kick once the clock is stopped
with <= 15 s or on 4th down. The kicking unit uses hurry tempo when trailing late (was a 32 s huddle,
which ended drives with the clock at zero). Must-kick on 4th down inside 2:30.

### D39. Tendencies keys are integers (bug fix that changes the benchmark)
`[ ]` The exported tendency keys carried "4.0" for the down while the engine looked up "4", so the
auto-policy silently fell back to "short pass" for every call. All validation numbers before this
fix were measured against that broken policy.

### D40. Phase 2 exit measured on 1,001 Q4 spots x 100 sims
`[ ]` Overall sim 0.491 vs actual 0.506 (-1.5 pts), every score-margin bucket within 3 points,
Brier 0.1306 vs 0.1301 for nflverse vegas_wp, MAE vs vegas_wp 0.061. Two thin buckets are 5-7 points
low: one timeout left (n=188) and 0:31-1:00 on the clock (n=83); both are inside sampling noise at
n=100 sims but worth watching. `docs/phase2_validation.md`.

## Phase 3: grading, percentile, coaches

### D41. Grading options are the full call list plus situational actions
`[ ]` Offense: 5 run calls, QB sneak (when legal), 9 pass + 9 play-action (depth x direction), RPO,
screen, Hail Mary (30+ yards out), trick play, spike, kneel, FG (<= 68 yd), punt, timeout (clock
running). ~33 options. Defense: 4 looks + timeout. PAT: XP vs 2-pt. Kickoff: deep vs onside.
Tempo for every option = the player's chosen tempo (so the grade is about the call, not the pace).

### D42. "Best" excludes trick plays and Hail Marys unless you called one
`[ ]` PLAN.md: gadget samples are biased toward success. They are graded if chosen but never
proposed as the better call, and never set the bar.

### D43. Seeds: option i in round r uses Rng((seed + 1000003 r + 7919 i) mod 2^32)
`[ ]` Deterministic per (decision seed, option), identical in Python and TypeScript, so a reload
regrades to the same numbers.

### D44. Percentile uses the player's own decision points, not re-simulated virtual drives
`[ ]` Each graded decision already has (option, league q, gap) for every option. A virtual caller
with temperature tau picks at each of the player's states with weight q x exp(-gap / tau) and pays
that option's gap; 15% of callers use pure league frequency. Percentile = share of 2,000 callers whose
total cost exceeds yours (ties count half). This is the only version that runs on a phone; it ignores
that a different early call would have led to different later states.

### D45. Coach profiles from 2016+ late-game plays, six traits, min 150 plays
`[ ]` Traits are deltas vs the league rate in the same situation cell (down, distance, zone, score
state): pass rate, deep-shot share, 4th-down go rate, timeout rate, tempo (seconds between snaps),
2-pt rate. Coaches drive two things: the opponent's policy shift (multipliers on pass/deep/go) and
the "you coached like" nearest-neighbour match, which only cites traits with >= 3 supporting calls.

### D46. Phase 3 exit measured
`[ ]` One decision graded 5 times at 600/3000 sims: gap 1.5-5.1% (mean 2.5%, sd 1.3%), 4 yellow and
1 red. Percentile over 6 spots: always-best 90, softmax tau=0.01 73, tau=0.05 42, league 22, always-worst 0.
Python grade time 2.9 s per decision with 30 options; the TS port should be several times faster.
`docs/phase3_grading.md`. The color flip at the 4% edge is sampling noise; raise round2_sims or
widen yellow if playtests find it jarring.

### D47. Player trait deltas are shrunk toward zero: delta x n / (n + 4)
`[ ]` A three-call drive otherwise produces trait values 20x larger than any coach's career average,
which made the nearest-coach match meaningless. Reasons are cited only for traits with >= 3 supporting
calls whose shrunk delta exceeds one league standard deviation and matches the coach's sign.

## Phase 4: TypeScript engine, workers, packing

### D48. Data packing: one gzipped binary per file, JSON header + raw little-endian typed arrays
`[ ]` `playbook.bin` holds only the 13 columns the engine needs (Int8 flags, Int16 yards) plus a
separate `hints` block (yac, time to throw, target, route, pressure, coverage, personnel, formation)
that only the main thread reads for animation. Decoded with DecompressionStream('gzip') in the
browser. `engine_data.json` stays JSON (0.7 MB). Alternatives: per-call-family lazy chunks (PLAN's
fallback if phones struggle) and SharedArrayBuffer (needs COOP/COEP headers). Not done yet.

### D49. One root package.json; Vite rooted at web/, engine/ imported by path
`[ ]` pnpm, TypeScript strict, vitest for engine tests, tsx for node scripts (parity harness). No
framework: the UI is plain TS + SVG per PLAN.md.

### D50. Parity target: event-for-event identical games on fixed seeds, WP values within 1e-9
`[ ]` Both engines consume the RNG in the same order; transcendental functions (exp, sqrt, log1p)
can differ in the last bit between CPython and V8, so values from the WP model are compared with a
tolerance rather than exactly. First run: 1195/1200 identical, 1200/1200 same final score; the five
differences were halftime WP values at the 1e-16 level. `engine/parity.ts`, `sim/parity_dump.py`.

### D51. Worker protocol: init (URLs or shared copies), grade (with progress), ping
`[ ]` The first worker fetches the data itself so grading can start early; once the main thread has
parsed its own copy it starts the remaining workers with structured-clone copies (no SharedArrayBuffer,
which needs cross-origin isolation headers). Jobs are FIFO with a priority field so the live snap's
grade jumps ahead of queued prefetch grades.

## Phase 5 prerequisites: ratings and lineups

### D52. Ratings v1 are per player-season from pbp box-score events plus participation snap shares
`[ ]` Own derivation (no Madden/PFF). QB: EPA per dropback + CPOE. RB: rush EPA/carry + receiving.
WR/TE: EPA and yards per target + target share. OL: the team's pass-protection (sack + pressure rate
allowed) and run-blocking (rush EPA) since pbp has no per-lineman events. DL/LB: sacks, QB hits, TFL,
tackles per snap. DB: pass break-ups and interceptions per snap plus team pass defense. K: FG make
minus model expectation. P: net yards vs the zone average. Each stat is shrunk toward the position
mean by n/(n+k), then blended with a snap-share prior (starter 0.5, rotational 0.3, backup 0.15)
before the percentile is mapped to 40-99 with rating = 40 + 59 x pct^0.67, so the median starter
lands near 77. Uses the whole season of the spot (a little hindsight for early-season spots).

### D53. Lineups come from the spot's real first play; 2026 falls back to the depth chart
`[ ]` 2023-2025 spots use the 22 participation ids on the spot's first snap (91% of the pool). 2026
has no participation, so the lineup is the latest depth chart's rank-1 players per position (QB, RB,
3 WR, TE, 5 OL; 4 DL, 3 LB, 4 DB), which is a generic 11 personnel rather than the real grouping.

## Phase 5: UI

### D54. Look: dark navy "chalkboard" field, Barlow / Barlow Condensed, amber + cyan accents
`[ ]` Deliberately not a green field and not the reference site's fonts. Rating colors run
red (<= 60) -> yellow (77) -> green (>= 90) via HSL hue. Mobile-first, max width 560px.

### D55. No framework: plain TypeScript, innerHTML templates, one render per screen, event delegation
`[ ]` The UI is small (home, intro, play, end, 5 modals). Vite builds it; the engine is imported by
path alias. Hash routes: #daily, #survivor, #daily/spot/ID, #daily/play/ID.

### D56. The player calls both sides of the ball until the final whistle (Q2 spots stop at halftime)
`[ ]` On the opponent's possessions the player picks the defensive look each snap (and may call a
timeout); PAT and kickoff choices are the player's when their team scores. Every one of these is a
graded decision that feeds the percentile. Alternative: grade only the offensive drive. Rejected
because the clock management on defense is half the fun of a two-minute drill.

### D57. The live snap is stepped on the main thread; the grade runs in the worker pool
`[ ]` The main thread keeps a full copy of the engine data (0.6 MB gz) so the snap is instant; the
grade of the same decision is queued with priority 1. Pending grades show "Grading your call… 37%".
The replay of a saved drive re-applies the stored actions with the same seed, which reproduces the
drive exactly (D43 makes regrades identical too), so no grade results are persisted.

### D58. Animation v1 is scripted keyframes, not physics
`[ ]` PLAN.md says "dots that teleport before investing in animation"; v1 is one step past that:
eased tweens for the carrier/target, the ball with an arc and shadow, a closing defender, line surge,
camera zoom. Honors prefers-reduced-motion and tap-to-skip. The Tier 1/2 physics model is not built.

### D59. Receiver/route picking and personnel/formation chips are not in the UI
`[ ]` The playbook rows carry target position, route, personnel, and formation, and the formation
drawn pre-snap follows the real lineup's position groups, but the dock offers type x depth x side
only. The hierarchical backoff for personnel cells and the two-layer grading are future work.

### D60. Daily scoring details
`[ ]` Day number = local days since `game.launch_date` (set to 2026-10-15 for development). Streak
counts consecutive local days with the scored drive finished. Stats update once per spot per day
(the first finish). Share string: name, day, percentile, up to 8 squares, coach verdict, URL.

### D61. Q2 spot result vs the real coach = points on your first possession vs the real drive's points
`[ ]` TD 7, FG 3, opponent TD -7, safety -2 for the real drive (from `fixed_drive_result`); yours is
the score change on the possession.

## Phase 6: backend and launch

### D62. API as specified in PLAN.md, with a few hard limits
`[ ]` `api/src/index.ts`: D1 schema verbatim; names <= 16 chars with a small profanity list; a name
is owned by the first device key that claims it; one daily result per key per date (first wins); dates
accepted within a +-1 day window around UTC today; scores clamped 0-100 (daily) / 0-500 (survivor).
Rate limiting is left to a Cloudflare rule. The site talks to it only when `VITE_API_BASE` is set,
so the game is fully playable with no backend.

### D63. GA4 events behind VITE_GA_ID
`[ ]` drive_start, call (grade, gap), drive_end (percentile, result, mode). Nothing loads when the id
is unset. drive_leave and survivor_end are not wired yet. No consent banner yet (needed for EU/UK).

### D64. OG image shipped as SVG; a PNG still needs rendering
`[ ]` `web/public/og.svg` is the design; `og:image` points at `/og.png`, which social crawlers need
as a raster. Render it once (e.g. with a browser screenshot at 1200x630) before launch.

## Phase 7: polish done so far

### D65. Adaptive defense uses mean yards (turnover = -45) per call x look from the library
`[ ]` edge(look) = recency-weighted average over your last 6 calls of (mean across looks minus mean
vs this look) / 3 yards, clipped to [-1, 1]; look weight = league q x exp(k x confidence x edge),
k = 2 (config). Only the live game adapts; grading sims use league look frequencies, so the grade
is "what would normally happen", not "what this defense was about to do". The toast fires after 4
straight runs (box loads) or 4 straight passes (blitz), per config.

### D66. Featured days: mechanism only
`[ ]` `pipeline/featured.json` is merged into game.json and the intro card shows the story, but no
stories are written (PLAN.md says write them yourself) and the schedule does not yet swap featured
spots in on specific days.

### D67. CI runs lint, pipeline tests and the type check; the weekly refresh rebuilds everything
`[ ]` The sim tests and parity need exported data, which is gitignored, so they run in the refresh
workflow after the pipeline, not in plain CI. Deploy is a commented-out wrangler step.

### D68. Some Q4 "tight" spots are degenerate (e.g. tied, 0:32 left, own 3, no timeouts)
`[ ]` Seen in Survivor. The Q4 filter only requires a one-score game; add a playability screen
(enough clock to matter, or inside midfield) alongside the Q2 filter from D17 before launch.

---

## Open items (not built)

- Receiver + route picking, personnel/formation chips, the playbook backoff on those keys, and the
  two-layer grade (PLAN "Deeper play-calling").
- Physics motion model (PLAN "Realistic movement", tiers 1 and 2). v1 is keyframe tweens.
- Ratings sheet is a list modal, not a zoomed field. Matchup adjustment of sampled rows by rating
  difference (PLAN step 3 of `step()`) is not applied; ratings are display-only so far.
- Featured-day stories (D66), Q2 and Q4 spot quality filters (D17, D68), kicker skill in the FG model.
- drive_leave / survivor_end analytics, cookie consent, OG PNG render, domain, AdSense, ads.txt.
- Deploy: Cloudflare Pages + Worker are configured but not deployed; nothing is committed to git yet.
