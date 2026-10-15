Rebuild Plan: Daily NFL Play-Calling Game
Oct 15, 2026 · @Luke
What the site is
Two-Minute Drill is a daily, Wordle-style NFL game. Each day you call the plays for one real late-game drive (2023–26, playoffs included), and a Monte Carlo simulator grades every call against what NFL play-callers would have done. It launched 2026-10-12, so it's brand new.
Core loop
1. A scenario card sets up a real spot: teams, score, clock, timeouts, down and distance, weather, and the point spread.
2. A top-down SVG field shows all 22 real players as dots, colored red→green by a 40–99 rating.
3. On offense you pick Run / Pass / RPO, plus situational buttons like timeout, spike, kneel, or FG. For a pass, you tap a receiver and cycle his route.
4. The engine samples a real NFL play that matches your call and the defense's look, then animates it with physically realistic movement.
5. After the snap, the call is graded green/yellow/red by the win-probability change versus the best option, measured over thousands of simulated game endings.
6. On defense you pick the look (light or loaded box, blitz or not) and special-teams calls.
7. The end card shows a percentile vs simulated NFL play-callers, a W-L-T record vs the real coach, the coach whose calls yours most resembled, a streak, an emoji-square share string, and today's global rank.
Modes
• Daily: three spot tiles a day (Two-minute drill · Protect the lead · Tied, or end of the half). One of them is the day's scored drive, and the type rotates daily. "Featured days" swap in a famous drive with a short story.
• Survivor: random real 4th quarters back to back. Each win keeps the run alive, and one loss ends it. Ties go to overtime under current NFL rules. Best runs post to a leaderboard.
What's under the hood (from the page source)
Piece
What it is
Size
index.html
One static page with inline CSS. Fonts are Big Shoulders Display and Libre Franklin.
41 KB
game.js
All UI, field rendering, animation, grading orchestration, and modes. Vanilla JS, no framework.
262 KB
motion.js
Player kinematics: speed, acceleration, and turning caps by position, from tracking data
24 KB
engine.js + game_worker.js
Simulator ported from a Python package, run in 2–3 Web Workers
78 KB + 9 KB
engine_data.json
Win-prob, kick, and clock models plus outcome tables, base64 typed arrays
5.4 MB
playbook.json
Library of real plays bucketed by call × defensive look × route
6.1 MB
game.json
740 spots, a 365-day schedule, 27 call types, league tendencies, 144 coach profiles
412 KB
spots/sNN.json
Per-spot rosters, ratings, kickers and punters, team tendencies (20 spots per chunk)
~220 KB each
Cloudflare Worker
/board (Survivor leaderboard) and /daily (today's scores)
—
Extras
Google Analytics events, AdSense only on between-game screens, localStorage progress
—
The data comes from the public nflverse play-by-play, plus Next Gen Stats averages for timing and depth. Ratings are the site's own: position percentiles blended with how the league values each player.
Ground rules: build your own, don't clone
Recreate the concept (daily play-calling against real NFL endings) with your own code, data, and brand. The game idea isn't protectable, but their files are someone else's work.
• Don't copy their game.js, engine.js, engine_data.json, playbook.json, spot files, CSS, copy, icons, or OG image. Don't point your app at their files or their Worker.
• Pick your own name and look. Avoid "Two-Minute Drill" plus a green field theme plus the same fonts. Possible directions: "Clutch Call", "Final Drive", "4th & Gold". Check that the domain and USPTO name are free.
• NFL IP: no NFL shield, team logos, or official uniforms. Team abbreviations and real player names used factually are common in fan games, but add a clear "not affiliated with the NFL" disclaimer on every screen.
• Data licensing: nflverse play-by-play is free (CC-BY / open). Credit it. Next Gen Stats public averages are fine to cite. Don't scrape gated NGS or PFF data.
• Ratings must be your own derivation, never Madden or PFF grades.
Architecture and tech stack
Ship a static site, an offline Python data pipeline, and one tiny edge API. All the heavy compute runs in the player's browser, so hosting costs about $0.
Layer
Choice
Why
Data pipeline
Python 3.12, nflreadpy / nfl_data_py, pandas, numpy, scikit-learn or LightGBM
nflverse is Python- and R-native, and you fit the models here
Simulator (reference)
A Python package (e.g. sim/) with unit tests
Easy to iterate and validate against real outcomes
Simulator (browser)
TypeScript port of the same logic, bundled to a Web Worker
Runs thousands of sims per decision off the main thread
Front end
Next.js (static export) or Vite + TypeScript, plain SVG for the field
Your existing stack. A canvas isn't needed for 22 dots.
Animation
Your own kinematics module (requestAnimationFrame)
Realistic player motion
API
Cloudflare Worker + D1 (SQLite) or KV
Leaderboard and daily scores at near-zero cost
Hosting
Cloudflare Pages or Vercel, static
CDN cache for multi-MB JSON
Analytics / ads
GA4 events, AdSense (later)
Same model as the reference
Repo layout
final-drive/
  pipeline/            # Python: ingest -> features -> models -> export
    ingest.py  spots.py  playbook.py  ratings.py  wp_model.py  coaches.py  export.py
  sim/                 # Python reference simulator + tests
  engine/              # TS port: engine.ts, worker.ts, rng.ts (seeded)
  web/                 # Next.js / Vite app
    public/data/       # exported game.json, engine_data.bin, playbook.bin, spots/*.json
    src/{field,anim,ui,modes,grading,store}/
  api/                 # Cloudflare Worker: /board, /daily
  scripts/build.py     # stamps build hash, packs + gzips data
Request flow on page load: index.html → game.json (spots + schedule) → today's spots/sN.json → workers fetch engine_data + playbook once (gzip, decoded with DecompressionStream) → play → POST result to /daily.
Cache-busting: stamp every asset URL with ?v=<git-sha> from a <meta name="build"> tag. Then a phone never mixes old and new data files.
Data pipeline
The pipeline is the real moat. It turns nflverse tables into five exported files, and it reruns weekly during the season.
1. Ingest (nflverse)
• load_pbp(2016..2026): play-by-play with EPA, WP, pass_length, pass_location, run_gap, air_yards, yards_after_catch, penalties, qb_kneel, qb_spike, timeouts, game_seconds_remaining.
• load_participation(): the 22 player IDs on the field per play, plus defenders_in_box, number_of_pass_rushers, offense_formation, defense_coverage_type, defense_man_zone_type, was_pressure, time_to_throw, route. This is what lets you show the real 22 and bucket by defensive look. Coverage of these fields is good from 2016 on, with gaps in recent seasons, so check each field.
• load_rosters_weekly(), load_players(), load_depth_charts(), load_injuries(), load_schedules() (spread, roof, temp, wind, coaches).
• load_ftn_charting() (2022+): play action, RPO, screens, motion, blitz. This is key for the RPO and play-action calls.
• Kicking: build a FG make model from pbp kick_distance × kicker × roof/wind.
2. Spot selection (spots.py, target 700+ spots)
• Q4 with ≤ 2:30 left and a one-score game, or Q2 with ≤ 2:00 left. Seasons 2023+.
• Classify each spot: drill (trailing ≤ 8, has the ball), protect (leading, has the ball), tight (tied, or end of half).
• Store the start state: {qtr, clock, down, ydstogo, yardline_100, score, timeouts_each, possession, receive_2h}. Also store weather, spread, and the real drive's calls and result (so you can score "vs the real coach").
• Hand-pick about 20 famous drives as "featured", each with a 1–2 sentence story you write yourself.
• Build a 365-day schedule: 3 spots a day (one per category), with the scored category rotating. Seed it deterministically from the date.
3. Play library (playbook.py)
• Map every real play to a call taxonomy (about 25–30 calls). Examples: RB inside/outside strong/weak, QB sneak, QB scramble, quick pass L/M/R, short, intermediate, deep, screen, play action, rollout, RPO, Hail Mary, spike, kneel, FG, punt, plus gadget plays like the flea-flicker and receiver pass.
• Bucket by defensive look: box ≤ 6 vs ≥ 7, × blitz (pass rushers ≥ 5) or not. That gives 4 looks.
• For each pass, keep the target's position (WR1, WR2, slot, TE, RB) and route. A user's receiver + route pick then samples real plays where that position ran that route.
• Each row stores: yards, clock runoff, out of bounds, first down, TD, turnover, return yards, penalty type and yards, sack, incomplete, plus animation hints (air yards, time to throw, coverage, pressure).
• Keep a minimum bucket size (around 30). Below that, fall back to the coarser bucket.
• Export as columnar typed arrays (Int16 / Float32), gzipped. Expect about 5–6 MB raw and roughly half that compressed.
4. Models (wp_model.py)
• Win probability from (score_diff, seconds_left, down, distance, yardline, timeouts × 2, spread, possession, receive_2h). Use logistic regression with interactions or a small GBM, exported as a lookup grid. You could also use nflverse vegas_wp as the training target. The simulator handles the actual endings. WP only values halftime or the point where a sim stops.
• Clock model: seconds between snaps by tempo (no-huddle, normal, milk) and by whether the clock is running.
• FG model: logistic on distance, with kicker skill, roof, wind, and temperature. Taper it past 52 yards to real long-range rates.
• Kickoff and punt outcome tables under 2024–25 kickoff rules (touchback to the 35).
• League tendencies (q): P(call | situation) for real NFL play-callers, plus a per-coach shift (pass rate, go-for-it, deep shots, 2-pt). These feed the "which coach you're like" result and the percentile.
5. Ratings (ratings.py)
• Per player, per week: position-specific stats (QB EPA/play and CPOE; WR/TE yards per route run and separation proxy; RB rush yards over expected; OL pressure allowed; DL/LB pressures and run stops; DB targets and yards allowed). Convert each to a position percentile, then map to 40–99 with 77 = typical starter.
• Blend in snap share or cap value as a "how the league values him" prior, so backups don't rate as elite on tiny samples.
• Export to spots/sNN.json: per team, the coach, QB, kicker, punter, the 22-man lineup with ratings, and team-level tendency shifts.
Export format
File
Contents
game.json
launch date, categories, calls[], schedule[365], featured{}, spots[] (state + real result + league q), coaches[]
spots/sNN.json
20 spots per chunk: rosters, ratings, K/P, team call shifts
engine_data.bin
WP grid, clock, FG, kickoff, punt, penalty tables
playbook.bin
outcome rows by call × look × route
Simulation engine and grading
The engine is a seeded Monte Carlo game-ending simulator. Every snap samples a real play from the library, and every decision is graded by playing out the rest of the game many times.
State object
{ t, qtr, clock_running, poss, down, togo, yl100, score:[a,b], tos:[a,b], phase: SNAP|PAT|KICKOFF|DONE, ot }
step(state, action, rng)
1. Apply the pre-snap runoff: tempo seconds if the clock is running, capped by the 40 s play clock, minus any timeout.
2. Pick the defense's look: league frequencies for this situation, tilted toward looks that beat the player's recent calls (adaptive defense, see below).
3. Sample a play row from playbook[call][look], or [route] for passes. Adjust it for the matchup: a small yardage shift by the rating difference between the offensive unit and the defensive unit.
4. Resolve the result: yards, first down, TD, turnover, penalty (accept or decline using the WP model), sack, out of bounds.
5. Apply the clock. Stop it on incomplete, out of bounds inside 2:00 / 5:00, a change of possession, or a score. Apply the two-minute warning.
6. Handle transitions: PAT or 2-pt try, kickoff (2025 rules), FG make or miss, punt, safety, end of half, overtime.
Opponent and auto-policy: when nobody is choosing (the other team's drive, or the rest of the game inside a sim), sample calls from league q shifted by that team's coach profile. Add sensible rules: kneel when ahead and able to run out the clock, spike to save a timeout, run it down then kick, onside kick when down two scores late.
Grading a decision (runs in workers while the play animates)
1. List the legal options in this state: Run / Pass / RPO × sub-calls, plus timeout, spike, kneel, FG, punt, go-for-it, 2-pt.
2. Round 1: simulate each option about 600 times to the end of the game (Q4) or to halftime (Q2), and record the mean win probability.
3. Round 2: re-simulate the top 3 plus the player's choice about 3,000 times on fresh seeds. This removes winner's-curse bias: the best of many noisy estimates looks better than it really is.
4. Compute gap = WP(best) − WP(yours). Color thresholds: green < 1%, yellow < 4%, red otherwise. Tune these with playtest data. Show "Better call: X (+3.2%)" only after the snap.
5. Exclude gadget plays from "better call" suggestions, since their charted samples are biased toward success.
6. Save the grading job (state, options, seed) to localStorage before the snap. A reload during the play can then regrade it with identical results.
Worker pool: use min(3, cores − 1) workers on desktop and 2 on phones. Start one worker immediately and the rest after the data has parsed. Give the snap itself and the call's facts priority over queued grading jobs. Use a seeded PRNG (mulberry32 or xoshiro128) so results are reproducible.
Adaptive defense: weight each look by exp(k · confidence · edge). Here edge (from −1 to +1) is how well that look does against the player's last N calls, with recent calls counting more. Tell the player when it kicks in ("They're loading the box: you've run 4 straight").
Daily percentile: simulate about 2,000 virtual play-callers. Each one picks with softmax weights q(option) · exp(−gap/τ), where τ is drawn log-uniform from 0.003 to 0.3, and 15% pick from pure league frequency. Percentile = the share whose total WP cost over the drive exceeds yours. Use the whole range of skill: a single τ bunches scores at 0 and 100.
"You coached like": compute per-trait deltas (pass rate, deep-shot rate, timeout aggression, go-for-it, tempo) of your calls minus league expectation in the same spots. Find the nearest coach profile, and only state the reasons the counts actually support.
Validate in Python first. Simulated endings from real start states should reproduce real win rates within about 2–3 points, both overall and by bucket (down 3 vs down 7, timeouts left). Then port to TS and diff the two engines on fixed seeds.
Front end: screens, field, animation
Build the app as one mobile-first page with hash routes (#daily, #survivor). The UI is small. Most of the effort goes into the field and the animation.
Screens
Screen
Contents
Header
Help (?) button, title + day label ("Day 4"), Stats button
Mode tabs
Daily · Survivor
Spot tiles
3 cards for today's spots, showing category, teams, score, clock, and done/locked state
Intro card
The scenario setup and a "Take the field" button. Featured days add the story.
Play view
Score bar (tap for game details), the SVG field, a rating legend, a "Player ratings" button, the call dock, and a collapsible play-by-play
Call dock
Offense: Run / Pass / RPO, then sub-calls, a tempo toggle (no-huddle, huddle, milk), and situational buttons. Pass mode: receiver cards with route names and odds. Defense: box × blitz looks. ST: FG block or ice, punt return.
Result chip
After each snap: the outcome call-out, the WP swing, the call grade color, and the better call if there was one
End card
Percentile (the big number), W-L-T vs the real coach, "you coached like ___", share button, streak, today's distribution and rank, top players, and an ad slot
Ratings sheet
Zoomed field with every rating, plus lists by unit
Modals
How to play (3 lines on the first visit, the full guide on ?), Stats (games, streak, histogram), Toast
Field (SVG)
• Use a coordinate system in yards: x from 0 to 53.3, y = L, where 0 is your goal line and 100 is theirs. Your end zone sits at the bottom.
• The camera shows the whole field pre-snap, then zooms to frame the play. Animate the viewBox.
• Draw formations from per-position templates. Offense: 5 OL, QB under center or in the gun, RB, WR/TE spread. Defense: the box count shows the look, and a blitz brings 2 defenders to the line.
• Each player dot is colored by rating: red (≤ 60) → yellow (77) → green (≥ 90). Show name tags pre-snap for skill players. Linemen show numbers only.
• Routes are drawn as paths from the receiver. Tapping a receiver cycles his route, and a second tap or the card button throws. Use a wide invisible hit area, because phones miss small SVG targets.
• Kickoff, FG, and punt formations follow current rules.
Animation (your own motion.ts)
• Each player gets max speed, acceleration, deceleration, and turn rate by position. Use public tracking norms, e.g. WR around 10 yd/s top speed.
• Script the play from the sampled row. Snap at about 0.25 s, then dropback, then routes. The throw comes at the charted time to throw (or the call's typical time), and the ball flies at about 24 yd/s. The catch lands at the charted air yards, then the run after the catch reaches the charted spot.
• Make outcomes look right. An incompletion shows a defender within about 3 yards breaking it up, or a visibly bad ball. Never show a wide-open drop. Tackles come from the nearest free defender at a pursuit angle, and forward progress never goes backwards.
• Show call-outs on the field: "SACKED!", "TOUCHDOWN!", "FLAG: HOLDING". Tap to skip. Respect prefers-reduced-motion.
• Run the grading in workers while the play animates, so the result chip is usually ready when the play ends.
State and persistence: keep everything in localStorage under a versioned key such as fd:v1. Store today's progress, pending grading jobs, the survivor run, stats, the streak, the player's name, and a random device key. Wrap every storage call in try/catch.
Share string, e.g.:
Final Drive #12 · 87th pct
🟩🟩🟨🟩🟥🟩  Beat the coach
yoursite.com
Use navigator.share on phones, falling back to the clipboard. Group long drives to at most 8 squares.
Deeper play-calling: personnel, formations, pass depth
Each offensive call becomes up to four quick taps: personnel → formation → play type → detail. Every one of them changes which real plays get sampled, which players are on the field, and how the defense lines up. nflverse participation data already tags every play with its personnel and formation, so this is data you can get, not something you invent.
The call flow
1. Personnel (who's on the field). Defaults to what you used last snap, or the team's most common grouping in this situation.
2. Formation (how they line up). Only the formations that fit the chosen personnel are shown.
3. Play type: Run · Pass · RPO · Screen · Play action, plus situational options (spike, kneel, FG).
4. Detail:
    ◦ Run: inside or outside, strong or weak side, QB sneak, or draw.
    ◦ Pass: Short / Medium / Deep, then left, middle, or right. Optionally pick the target receiver and route.
A "Quick call" button repeats the last personnel and formation, so a hurry-up drive is still one or two taps.
Personnel groups (the first digit is RBs, the second TEs; WRs make up the rest of the five skill players)
Group
Players
Typical use
11
1 RB, 1 TE, 3 WR
The default: about 60%+ of NFL snaps
12
1 RB, 2 TE, 2 WR
Balanced, play action
21
2 RB (FB), 1 TE, 2 WR
Downhill run, play action
13
1 RB, 3 TE, 1 WR
Short yardage
22
2 RB, 2 TE, 1 WR
Power run
10 / Empty
0–1 RB, 0 TE, 4–5 WR
Two-minute drill, spread passing
Goal line (23 / jumbo)
Extra OL or TEs
Inside the 2, 4th and 1
Formations (nflverse offense_formation): Shotgun, Singleback (under center), I-form, Pistol, Empty, Jumbo, Wildcat. Add a strength toggle (strength right or left) and optionally "bunch" or "trips" for 3-WR sets. Draw each formation from an alignment template (x offset and depth for each slot), so switching formations visibly moves players before the snap.
Pass depth (bucketed on the real play's air_yards)
Depth
Air yards
What it trades
Short
Behind the line to 9
High completion rate, keeps the clock moving unless thrown to the sideline
Medium
10–19
Moves the chains, tighter windows
Deep
20+
Big-play chance, more incompletions and interceptions, stops the clock when it falls incomplete
Compute the real completion, interception, sack, and yards-after-catch rates per bucket from the data. Don't hand-set them. nflverse's own pass_length field only has short and deep (split at 15 air yards), so derive the three buckets from air_yards. Pressure and sack rates also rise with depth, because deep routes take longer to develop.
Data changes (playbook.py)
• Add keys to every play row: personnel (parse offense_personnel into the group code), formation, depth (from air_yards), and direction (from pass_location / run_location).
• Sparsity is the main problem. Personnel × formation × call × depth × defensive look gives thousands of cells, and many have only a handful of plays. Use hierarchical backoff: sample from the most specific cell that has ≥ 30 plays. Otherwise drop formation, then personnel, but always keep call + depth + look.
• When you back off, keep the effect of the choice anyway: fit a small regression of yards and success on personnel and formation. Then reweight or shift the sampled rows by that effect, so picking 12 personnel still means something even in a sparse cell.
• Use plays from 2016 on for depth. Participation coverage is good for most seasons, but check each field per season.
Effects that make choices matter
• The defense reacts to personnel. Sample the defense's personnel (base 4-3/3-4, nickel, dime) from the real distribution against that offensive group. 11 personnel mostly draws nickel, while 12, 21, and 22 draw base. Then sample the box count and blitz from that. Heavy personnel invites a loaded box, which helps play action and hurts the run, as in real football.
• Players change. Personnel decides who steps on: TE2 or a fullback instead of WR3, taken from that game's depth chart or the players who actually played (participation). Their ratings feed the matchup adjustment, so going heavy with a weak TE2 has a cost.
• Formations change tendencies. Under center boosts run and play-action success, and shotgun boosts quick passing. Let the data's regression set the size of each effect.
• The clock: deep incompletions stop the clock, short completions in the middle keep it running, and sideline throws stop it if the receiver gets out of bounds. That makes depth a real two-minute-drill decision.
Grading with more options
• The option tree is now big: about 7 personnel × 5 formations × 15 calls is hundreds of combinations, too many to simulate thousands of times on a phone.
• Grade in two layers:
    1. The call, given your personnel and formation. Run the full two-round grading over play type × depth × direction (about 15–20 options).
    2. The personnel and formation choice itself, graded lightly. Compare yours against the 3–4 most common alternatives in this situation, each paired with its best call, at about 300 sims each.
• Show both results: "Good call from 12 personnel. Best overall: 11 Shotgun, medium pass right (+1.8%)".
• The AI opponent and the simulated play-callers choose personnel and formation by league frequency in the situation, shifted by each coach's tendencies.
UI notes
• Personnel and formation appear as a compact chip row above the play-type buttons. The field updates live while you change them (players jog to the new alignment).
• Pass depth appears as three big buttons with a small "typical gain / completion" hint under each, drawn from the real data for this spot. That teaches the trade-off without saying which is best.
• On defense, mirror the flow: personnel (base / nickel / dime), then the look (box, blitz, coverage shell).
Realistic movement and physics
Move every player with a physics simulation, not tweens. Each of the 22 is an agent with mass, velocity, and heading, stepped at 60 Hz under speed, acceleration, and turning limits. The play's outcome is fixed in advance, and a planner picks paths that reach it without breaking those limits.
Scope: good enough first, perfect later. Build tier 1 first. It already fixes most of what looks fake. Tier 2 is optional polish.
Tier
What's in it
Effort
1. MVP motion
Locomotion limits (section 2), reaction delays, facing ovals, the separation force, a ball arc with a shadow, a spring camera, and a simple planner that fixes only the catch time and spot and the tackle time and spot
~1–2 weeks
2. Polish
Spring-damper blocking, momentum tackles, broken tackles, the iterative outcome planner, motion trails, after-whistle behavior
~2–4 weeks, any time later
Why motion usually looks fake
• Linear or eased tweens between points: constant speed, instant starts and stops.
• Direction changes with no slowdown, so players "slide" around corners.
• Dots overlapping or passing through each other, and no visible contact.
• Everyone moves at the same speed, and defenders react before the snap.
• The ball moves in 2D with no arc, and tackles happen with nobody touching the carrier.
1. Simulation loop
• Use a fixed 60 Hz physics step that's independent of frame rate, then interpolate positions for rendering. A 120 Hz phone and a 30 Hz phone then play the same play.
• Pre-bake the whole play (about 4–8 s, 22 agents × ~480 steps) in a worker before it animates. Playback is then just reading arrays, and "tap to skip" is free.
• Seed everything, so a replay is identical.
2. Locomotion model (per player, per step)
• Acceleration falls off with speed: a = aMax × (1 − v / vMax). Players explode off the line, then level out, which is how sprint curves look in tracking data.
• Braking is stronger than accelerating: use about 1.3–1.5 × aMax, but it still takes 2–3 yards to stop at full speed.
• Turning is limited by lateral grip: at speed v the tightest turn radius is r = v² / aLat. A sharp cut forces a slowdown first (plant and cut). A gentle bend can be run at full speed.
• Movement depends on facing: backpedalling tops out around 60% of forward speed, and turning the hips costs about 0.2–0.3 s. That's what makes a corner get beat on a double move.
• Reaction delay: defenders start 0.15–0.35 s after the snap or the throw, scaled by rating. The offense moves on the snap count.
• Ratings matter: scale vMax, aMax, and reaction time by ±5% with the player's rating, so an elite receiver visibly separates.
Starting values to tune (approximate, check them against public NFL Next Gen Stats speed figures):
Position
Top speed (yd/s)
Max accel (yd/s²)
Lateral grip (yd/s²)
Mass (lb)
WR / CB
9.5–10.5
5.0
7.0
195
RB / S
9.0–10.0
5.0
7.0
210
TE / LB
8.5–9.3
4.3
6.0
245
QB
8.0–9.5
4.2
6.0
220
DL edge
8.0–8.8
4.0
5.0
265
OL / DT
6.8–7.8
3.4
4.0
310
A sketch of one step:
function stepAgent(p: Agent, desired: Vec, dt: number) {
  const speed = len(p.vel);
  const want = clampLen(desired, p.vMax * facingFactor(p, desired));
  let dv = sub(want, p.vel);
  // split into along-track (speed up / brake) and lateral (turning) parts
  const fwd = speed > 0.1 ? norm(p.vel) : norm(want);
  const along = dot(dv, fwd), side = sub(dv, mul(fwd, along));
  const aAlong = along > 0 ? p.aMax * (1 - speed / p.vMax) : p.aBrake;
  dv = add(mul(fwd, clamp(along, -aAlong * dt, aAlong * dt)),
           clampLen(side, p.aLat * dt));
  p.vel = add(p.vel, dv);
  p.pos = add(p.pos, mul(p.vel, dt));
  p.heading = turnToward(p.heading, angle(p.vel), p.turnRate * dt);
}
3. Steering: what each player wants to do
• Routes are waypoint paths with named break points. At each break the receiver brakes in proportion to the cut angle, then re-accelerates. Speed alone sells the route (a 90° out costs about 2 yd/s, a post costs very little).
• Pursuit aims at the predicted intercept point, not where the carrier is now. Solve for the earliest time t at which the defender can reach the carrier's projected position. That gives real pursuit angles.
• Coverage: man defenders mirror with a cushion and lag by their reaction time. Zone defenders drop to a landmark, then break on the ball after the throw with their reaction delay.
• Separation force: a short-range repulsion (boids-style) keeps bodies about 0.8 yd apart unless they're engaged. This alone removes most of the "dots through dots" look.
• Blend behaviors with weights per role and phase (pre-throw, ball in air, after the catch).
4. Line play and contact
• Model each block as a pair joined by a spring-damper at about 0.6 yd. Each side pushes with force ∝ mass × strength rating. The net force moves the pair, so a dominant rusher visibly collapses the pocket.
• Pass protection drifts back on a timeline: the pocket depth grows about 1 yd/s, and the edges arc around the QB. Run blocking drives forward and toward the play side.
• A block "sheds" when accumulated advantage passes a threshold, or at a scripted time for a sack or pressure. The rusher then pursues the QB with intercept steering.
• Tackles use momentum: compare the carrier's momentum to the tackler's. A heavy back hit head-on falls forward 1–2 yd. A carrier hit from the side goes down sideways. Gang tackles add a second contact. Broken tackles are a brief contact that slows the carrier by about 30% before he re-accelerates.
5. Ball physics
• Treat the ball as a 3D projectile under gravity. Pick the launch angle from the throw type (a line drive at about 10–15°, a deep shot at about 30–40°) and solve for the speed that hits the catch point at the charted time.
• Top-down, show height with a ground shadow that separates from the ball and a ball that scales up 10–30% at the apex. Add a subtle spiral rotation.
• Handoffs and pitches are short arcs timed to the mesh point. Punts and kickoffs use high arcs with about 4–4.5 s of hang time.
6. Outcome-constrained planning (the hard part)
The sampled real play fixes the result (e.g. a 14-yard catch, tackled at the 37). Physics alone won't land there, so plan backwards:
1. Fix the anchors: the catch point and time, and the down spot and time.
2. Give the receiver a route that reaches the catch point at that time, then pick the separation of the nearest defender to match the outcome (tight for an incompletion, loose for a big gain).
3. Choose the tackler, and solve for the reaction delay or start position that gets him to the down spot on time, within his limits.
4. Simulate forward with steering. Wherever a constraint is missed, nudge timing and start positions, never the speed caps. Iterate 2–3 times in the worker.
5. If it's still infeasible, pick a different tackler or a slightly different route rather than letting anyone run faster than allowed.
7. Making it read as football
• Draw players as small ovals with a facing notch (or a jersey number rotated to the heading), not round dots. Heading is half of what makes motion look real.
• Add a subtle lean into acceleration and turns, and optional short fading motion trails during the play.
• Follow with a camera driven by a critically damped spring on the ball and carrier, so it never snaps or jitters. Zoom smoothly at the snap.
• After the whistle, players decelerate naturally, drift toward the pile, and jog back. Nobody freezes in place.
• Render with SVG transform updates (or canvas if SVG is slow on phones), and respect prefers-reduced-motion.
8. Calibration data
• Free and safe: public Next Gen Stats figures for top speeds, time to throw, separation, and air yards, plus your own nflverse charting.
• NFL Big Data Bowl tracking data (10 Hz positions for every player) is ideal for fitting acceleration curves, route speed profiles, and pursuit angles. Read its competition terms first: they typically limit use to the competition and non-commercial research. At most, use it offline to fit parameters, and never ship its rows.
• Film reference: watch all-22 and broadcast clips of the same play types and compare side by side.
9. Validation checklist
[ ] Speed and acceleration histograms per position fall inside realistic ranges; no frame exceeds vMax or aMax
[ ] No two unengaged players closer than 0.6 yd
[ ] Every cut sharper than 60° shows a slowdown
[ ] Ball carriers are always tackled by someone in contact; forward progress never goes backward
[ ] Incompletions always show a defender near the ball or a visibly bad throw
[ ] A debug overlay (velocity arrows, intercept points, block springs) can be toggled with a URL flag such as ?debug=1
[ ] Playtesters rate 20 random plays for "looks real" (1–5) before and after each change
Game modes, scoring, leaderboard
There are two modes. Daily is the retention hook, and Survivor is the endless mode. Both are scored with the same grading engine.
Daily
• Day number = days since launch, computed in the player's local date. A drive started before midnight still counts for that day.
• 3 tiles a day. One scored drive counts toward the percentile and the global board, and the other two are practice. Lock the scored drive after it's finished.
• Score = percentile vs simulated play-callers. Secondary: the actual result vs the real coach. In Q4 that's win/loss. In Q2 it's the points the possession was worth (TD 7, FG 3, defensive TD −7, safety −2).
• Streak = consecutive days finished, including today.
Survivor
• Draw random Q4 spots from the pool with no repeats until the pool is exhausted. Each spot is played to the final whistle.
• A win keeps the run going, a loss ends it, and a regular-season OT tie keeps it alive without adding a win.
• Overtime follows the 2025 rules: both teams get a possession, 10:00 (15:00 in the playoffs), 2 timeouts (3 in the playoffs), and a seeded coin toss.
• The "how it ended" card shows the costliest calls of the game you lost.
Leaderboard API (Cloudflare Worker + D1)
Endpoint
Body / response
Notes
GET /board
{rows:[{name,best,at}]} top 50
Survivor best runs
POST /board
{name, key, best} → {rows, taken}
key = a random device token. The first key to claim a name owns it, and lower scores are ignored.
POST /daily
{date, key, name?, score, spots:[…]} → {rank, n, histogram, spotAvgs, top}
Only the first result per key per date counts
GET /daily?date=
same summary
For the end card
• Send POSTs as text/plain JSON so they stay CORS-"simple" requests with no preflight. Allow only your origin.
• Anti-cheat (light): sanity-check score ranges, rate-limit by IP and key with a Cloudflare rate limit, and reject dates other than today or yesterday. Optionally have the client send its call list and seed so the Worker can spot-check.
• Profanity-filter the names and cap them at 16 characters.
D1 schema
CREATE TABLE board (slug TEXT PRIMARY KEY, name TEXT, key_hash TEXT, best INT, at INT);
CREATE TABLE daily (date TEXT, key_hash TEXT, name TEXT, score REAL, spots TEXT, at INT,
                    PRIMARY KEY (date, key_hash));
CREATE INDEX daily_score ON daily(date, score);
Launch: hosting, analytics, ads, legal
Launch on a free static host with an analytics event schema from day one, and hold ads until there's real traffic.
• Hosting: Cloudflare Pages, plus _headers for long-cache immutable data files (they're versioned by ?v=) and a short cache on index.html. Pick a custom domain.
• Social: a 1200×630 OG image you design yourself, summary_large_image Twitter card tags, theme-color, apple-touch-icon, and viewport-fit=cover for notched phones.
• Analytics (GA4 events): drive_start, call (call type, grade, gap), drive_end (percentile, result), share, drive_leave (abandoned mid-drive: calls made, seconds, still loading?), survivor_end (games). Watch completion rate and load-time drop-off. The data files are multi-MB, so show download progress.
• Ads: AdSense only on between-game screens (end card, intro), never during a drive, and labeled "Ad". Apply only after you have content and traffic, since approval needs both. Add ads.txt.
• Legal pages: Privacy (GA, AdSense cookies, localStorage, leaderboard names), Terms, and a disclaimer: "Not affiliated with the NFL or its teams; data from nflverse." Use a cookie consent banner if you target the EU or UK.
• Performance budget: first paint < 1 s, first snap ready < 4 s on 4G. Ship the data gzipped, decode it in workers, and drop references after parsing. Test on a mid-range Android.
• Season refresh: a GitHub Action reruns the pipeline weekly (nflverse updates nightly in season), regenerates spots and ratings, and redeploys.
Phased roadmap
Plan on about 10–12 weeks of nights and weekends to an MVP. Simplify first: get a playable, graded drive with dots that "teleport" before investing in animation.
1. Weeks 1–2: Data foundation. Pull nflverse pbp, participation, and FTN data for 2016–26. Build the call taxonomy and look buckets, then extract 700+ spots. Exit: a notebook showing bucket counts ≥ 30 for 90% of call × look cells.
2. Weeks 3–4: Python simulator. Write the state machine, clock, PAT/kickoff/FG/punt, WP model, and auto-policy. Exit: simulated win rates from real start states land within 3 points of actual results.
3. Week 5: Grading + percentile. Add the two-round evaluation, the virtual play-caller distribution, and coach profiles. Exit: grades are stable across seeds, and the percentile spreads 0–100 for test policies.
4. Weeks 6–7: TS engine + workers. Port the simulator, pack the data, build the worker pool, and add the seeded RNG. Exit: TS output matches Python on 1,000 fixed-seed games, and a grade takes < 2 s on a phone.
5. Weeks 7–9: UI MVP. Build the tiles, intro, static SVG field with rated dots, call dock (with Short / Medium / Deep pass depth from day one), result chip, end card, share, and localStorage. Exit: 10 friends play daily for a week.
6. Week 10: Backend + launch. Add the Worker, D1, /daily, /board, GA events, OG image, legal pages, and domain. Soft-launch on r/nfl-adjacent subs and X.
7. Weeks 11–14: Polish. Build the physics motion model in this order: locomotion limits, then steering and separation, then line play, then ball flight, then outcome planning (see Realistic movement), personnel and formation switching (playbook backoff plus defensive personnel response), pass routes and receiver picking, adaptive defense, Survivor plus OT, featured days, and the ratings sheet.
8. Later: AdSense, push or email reminders, weekly data refresh, "this week's real game" spots, and private friend leagues.
Biggest risks: participation-data gaps in the newest seasons (fall back to formation templates), the phone performance of 5 MB+ of data (lazy-load the playbook per call family), and grades that feel "rigged" (always show the better call with its margin, and draw outcomes believably).
Sources
• Reference site, page source and public assets reviewed 2026-10-15
• nflverse: play-by-play, participation, rosters, schedules, FTN charting