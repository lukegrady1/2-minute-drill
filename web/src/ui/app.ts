/** Views and the hash router. Plain DOM, one render() per screen. */
import type { EngineData } from "@engine/data";
import { DONE, isDone, type Action } from "@engine/engine";
import type { WorkerPool } from "@engine/pool";
import type { Spot } from "@engine/simulate";
import { animatePlay, type Hints } from "../anim/anim";
import { loadSpotFile, type GameJson, type SpotFile } from "../data";
import { FieldView, formation, type Scene } from "../field/field";
import { dailySeed, todaysSpots } from "../modes/daily";
import { survivorOrder, survivorSeed } from "../modes/survivor";
import { Session, labelOf, type Decision } from "../session";
import { load as loadStore, update, type DriveSave } from "../store/storage";
import { renderDock, type DockState } from "./dock";
import { clockStr, downStr, el, esc, ordinal, pct, ratingColor, spotTitle, todayKey } from "../util";
import { postBoard, postDaily, track } from "../api";

export interface AppDeps { game: GameJson; data: EngineData; pool: WorkerPool; hints: Record<string, Int8Array | Int16Array> | null }

type Route = { view: "home"; tab: "daily" | "survivor" } | { view: "intro"; spotId: string; mode: "daily" | "survivor" } | { view: "play"; spotId: string; mode: "daily" | "survivor" };

export class App {
  root = document.getElementById("app")!;
  route: Route = { view: "home", tab: "daily" };
  sess: Session | null = null;
  file: SpotFile | null = null;
  field: FieldView | null = null;
  ds: DockState = { mode: "pass", depth: "short", tempo: "normal" };
  busy = false;
  skip = { skip: false };
  lastLook: { box: "light" | "heavy"; blitz: boolean } | null = null;
  toastTimer = 0;

  constructor(public deps: AppDeps) {
    window.addEventListener("hashchange", () => this.onHash());
    this.root.addEventListener("click", (e) => this.onClick(e));
    this.onHash();
  }

  // ---- routing
  onHash(): void {
    const h = location.hash.replace(/^#\/?/, "");
    const [a, b, c] = h.split("/");
    if (a === "survivor" && !b) this.route = { view: "home", tab: "survivor" };
    else if ((a === "daily" || a === "survivor") && b === "spot" && c) this.route = { view: "intro", spotId: c, mode: a };
    else if ((a === "daily" || a === "survivor") && b === "play" && c) this.route = { view: "play", spotId: c, mode: a };
    else this.route = { view: "home", tab: "daily" };
    this.render();
  }
  go(hash: string): void { location.hash = hash; }

  // ---- shared chrome
  header(sub: string): string {
    return `<div class="hdr"><button class="ghost" data-modal="help" aria-label="How to play">?</button><div style="text-align:center"><h1>${esc(this.deps.game.name)}</h1><div class="day">${esc(sub)}</div></div><button class="ghost" data-modal="stats" aria-label="Stats">Stats</button></div>`;
  }
  footer(): string {
    return `<footer>${esc(this.deps.game.disclaimer)} Play-by-play data from <a href="https://github.com/nflverse" rel="noopener">nflverse</a> (CC-BY-4.0). Ratings are our own derivation.<br><a href="#" data-modal="privacy">Privacy</a> · <a href="#" data-modal="terms">Terms</a></footer>`;
  }
  toast(msg: string): void {
    document.querySelector(".toast")?.remove();
    document.body.appendChild(el(`<div class="toast">${esc(msg)}</div>`));
    clearTimeout(this.toastTimer);
    this.toastTimer = window.setTimeout(() => document.querySelector(".toast")?.remove(), 2200);
  }

  render(): void {
    const r = this.route;
    if (r.view === "home") this.renderHome(r.tab);
    else if (r.view === "intro") this.renderIntro(r.spotId, r.mode);
    else this.renderPlay(r.spotId, r.mode);
  }

  // ---- home
  renderHome(tab: "daily" | "survivor"): void {
    const g = this.deps.game;
    const store = loadStore();
    const { day, spots } = todaysSpots(g);
    const today = todayKey();
    const prog = store.progress[today] ?? {};
    let body = `<div class="tabs"><button class="${tab === "daily" ? "on" : ""}" data-go="daily">Daily</button><button class="${tab === "survivor" ? "on" : ""}" data-go="survivor">Survivor</button></div>`;
    if (tab === "daily") {
      body += spots.map(({ cat, spot, scored }) => {
        const p = prog[spot.id];
        const badge = p?.status === "done" ? `<span class="badge done">Done · ${Math.round(p.percentile ?? 0)}th</span>` : scored ? `<span class="badge scored">Today's scored drive</span>` : `<span class="badge">Practice</span>`;
        return `<div class="card tile" data-go="daily/spot/${spot.id}"><div class="cat">${esc(cat.label)}</div>${badge}<div class="state">${this.spotLine(spot)}</div><div class="muted" style="font-size:12px">${spot.season} wk ${spot.week}${spot.playoff ? " playoffs" : ""}</div></div>`;
      }).join("");
    } else {
      const run = store.survivor.run;
      body += `<div class="card"><h2>Survivor</h2><p class="muted">Random real 4th quarters, back to back. Win and the run lives; lose and it ends. Ties in overtime keep it alive.</p>
        <div class="stat"><div><b>${run?.alive ? run.wins : 0}</b><span>Current run</span></div><div><b>${store.survivor.best}</b><span>Best run</span></div></div>
        <div class="row" style="margin-top:12px"><button class="primary grow" data-survivor="${run?.alive ? "continue" : "new"}">${run?.alive ? "Continue the run" : "Start a run"}</button></div></div>`;
    }
    this.root.innerHTML = this.header(`Day ${day + 1}`) + body + this.footer();
    if (!store.seenHelp) { update((s) => { s.seenHelp = true; }); this.openModal("help"); }
  }
  spotLine(spot: Spot): string {
    const st = spot.state;
    return `${esc(spot.off)} ${st.score[0]}–${st.score[1]} ${esc(spot.def)} · Q${st.qtr} ${clockStr(st.clock)} · ${downStr(st.down, st.togo, st.yl)} at ${spotTitle(st.yl, spot.off, spot.def)}`;
  }

  // ---- intro
  renderIntro(spotId: string, mode: "daily" | "survivor"): void {
    const spot = this.deps.game.spots.find((s) => s.id === spotId);
    if (!spot) { this.go("daily"); return; }
    const st = spot.state;
    const cat = this.deps.game.categories.find((c) => c.id === spot.cat)!;
    const feat = this.deps.game.featured[spot.id];
    const weather = spot.ctx.roof === "dome" || spot.ctx.roof === "closed" ? "Indoors" : spot.ctx.temp == null ? "Outdoors" : `${spot.ctx.temp}°F, wind ${spot.ctx.wind ?? 0} mph`;
    const spread = spot.ctx.spread == null ? "" : spot.ctx.spread > 0 ? `${esc(spot.off)} favored by ${spot.ctx.spread}` : spot.ctx.spread < 0 ? `${esc(spot.def)} favored by ${-spot.ctx.spread}` : "Pick 'em";
    this.root.innerHTML = this.header(cat.label) + `
      <div class="card"><h2>${esc(spot.off)} at the ${esc(spotTitle(st.yl, spot.off, spot.def))}</h2>
        ${feat ? `<p><b>${esc(feat.title)}</b> ${esc(feat.story)}</p>` : ""}
        <p>${esc(cat.blurb)} You are <b>${esc(spot.off)}</b>${st.score[0] < st.score[1] ? `, down ${st.score[1] - st.score[0]}` : st.score[0] > st.score[1] ? `, up ${st.score[0] - st.score[1]}` : ", tied"} with <b>${clockStr(st.clock)}</b> left in Q${st.qtr}. ${downStr(st.down, st.togo, st.yl)}, ${st.tos[0]} timeout${st.tos[0] === 1 ? "" : "s"} (they have ${st.tos[1]}).</p>
        <p class="muted">${spot.season} week ${spot.week}${spot.playoff ? ", playoffs" : ""} · ${esc(spot.home)} vs ${esc(spot.away)} · ${weather} · ${spread}</p>
        <p class="muted">${st.qtr === 2 ? "You play to halftime; the half is valued by the win-probability model." : "You call both offense and defense to the final whistle, overtime included."}</p>
        <button class="primary" style="width:100%" data-go="${mode}/play/${spot.id}">Take the field</button></div>` + this.footer();
  }

  // ---- play
  async renderPlay(spotId: string, mode: "daily" | "survivor"): Promise<void> {
    const spot = this.deps.game.spots.find((s) => s.id === spotId);
    if (!spot) { this.go("daily"); return; }
    if (!this.sess || this.sess.spot.id !== spotId) {
      this.root.innerHTML = this.header("Loading the spot…") + `<div class="card"><div class="progress"><i style="width:60%"></i></div></div>`;
      const file = await loadSpotFile(spot);
      const store = loadStore();
      const today = todayKey();
      const seed = mode === "daily" ? dailySeed(spot.id, today) : survivorSeed(store.survivor.run?.seed ?? 1, store.survivor.run?.index ?? 0);
      this.file = file;
      this.sess = new Session(this.deps.data, spot, file, this.deps.pool, seed, this.deps.game.coaches);
      this.sess.onGrade = (d) => this.onGrade(d);
      this.sess.onProgress = (d, done, total) => this.onGradeProgress(d, done, total);
      this.ds = { mode: "pass", depth: "short", tempo: this.sess.defaultTempo() };
      this.lastLook = null;
      // replay a saved drive (actions only; the seed makes it identical)
      const saved = store.progress[today]?.[spot.id];
      if (mode === "daily" && saved && saved.actions.length) {
        for (const a of saved.actions as Action[]) { if (this.sess.state.phase === DONE) break; this.sess.act(a); }
      }
      this.sess.autoAdvance();
    }
    this.drawPlayScreen();
  }

  drawPlayScreen(): void {
    const sess = this.sess!, s = sess.state, spot = sess.spot;
    const me = spot.off, them = spot.def;
    const mid = s.phase === DONE ? "FINAL" : `Q${s.qtr > 4 ? "OT" : s.qtr} <b>${clockStr(s.clock)}</b>${s.phase === "snap" ? `${downStr(s.down, s.togo, s.yl)} · ${s.poss === 0 ? me : them} ball at ${spotTitle(s.yl, s.poss === 0 ? me : them, s.poss === 0 ? them : me)}` : s.phase.replace("_", " ")}`;
    const scorebar = `<div class="scorebar"><div><div class="team me">${esc(me)} ${s.score[0]}</div><div class="tos">${"●".repeat(s.tos[0])}${"○".repeat(Math.max(0, 3 - s.tos[0]))}</div></div><div class="mid">${mid}</div><div class="right"><div class="team">${s.score[1]} ${esc(them)}</div><div class="tos">${"●".repeat(s.tos[1])}${"○".repeat(Math.max(0, 3 - s.tos[1]))}</div></div></div>`;
    const wp = sess.wp();
    const last = sess.decisions[sess.decisions.length - 1];
    const chip = last ? this.chipHtml(last) : `<div class="chip"><div class="bar"></div><div><div class="main">Win probability ${pct(wp, 0)}</div><div class="sub">Make the call. Every snap is graded against thousands of simulated endings.</div></div></div>`;
    const dock = s.phase === DONE ? `<div class="dock"><button class="primary" style="width:100%" data-finish="1">See the result</button></div>` : renderDock(sess, this.ds, () => {}, () => {});
    const pbp = `<details class="card"><summary>Play by play (${sess.log.length})</summary><div class="pbp">${sess.log.slice().reverse().map((e) => `<div>${e.kind === "period" || e.kind === "warning" ? "— " : ""}${esc(e.text)}${e.kind === "play" ? ` <span class="muted">(${esc(e.call.replace(/_/g, " "))})</span>` : ""}${e.ended ? " — clock expires" : ""}</div>`).join("")}</div></details>`;
    this.root.innerHTML = this.header(`${this.route.view === "play" && (this.route as { mode: string }).mode === "survivor" ? "Survivor" : "Daily"} · ${spot.season} wk ${spot.week}`) + scorebar +
      `<div class="field-wrap"><div id="field"></div><div class="callout" id="callout"></div></div>
      <div class="legend"><span><i style="background:${ratingColor(55)}"></i>&lt;60</span><span><i style="background:${ratingColor(77)}"></i>77 starter</span><span><i style="background:${ratingColor(92)}"></i>90+</span><span class="grow"></span><button class="ghost" style="min-height:32px;padding:4px 10px;font-size:12px" data-modal="ratings">Player ratings</button></div>` +
      chip + dock + pbp + this.footer();
    this.field = new FieldView(document.getElementById("field")!);
    this.drawField();
  }

  scene(): Scene {
    const sess = this.sess!, s = sess.state;
    const shotgun = this.ds.mode !== "run" || s.down >= 3;
    return formation(s, this.file!.off.players, this.file!.def.players, this.lastLook, shotgun);
  }
  drawField(): void {
    const s = this.sess!.state;
    const sc = this.scene();
    const fdL = s.phase === "snap" ? (s.poss === 0 ? 100 - s.yl + s.togo : s.yl - s.togo) : null;
    this.field!.render(sc, fdL !== null && fdL > 0 && fdL < 100 ? fdL : null);
  }

  chipHtml(d: Decision): string {
    const g = d.grade;
    const swing = d.wpAfter - d.wpBefore;
    const swingTxt = `${swing >= 0 ? "+" : ""}${(100 * swing).toFixed(1)}% WP`;
    const text = d.events.map((e) => e.text).filter(Boolean).slice(0, 2).join(" · ");
    if (!g) return `<div class="chip" id="chip"><div class="bar"></div><div><div class="main">${esc(text)} <span class="muted">${swingTxt}</span></div><div class="sub" id="chip-sub">Grading your call… <span id="chip-prog"></span></div></div></div>`;
    const verdict = g.color === "green" ? "Good call." : g.color === "yellow" ? "Fine, not best." : "Costly.";
    const better = g.better ? `Better call: ${esc(g.better.replace(/_/g, " "))} (+${(100 * g.gap).toFixed(1)}%)` : "That was the best option.";
    return `<div class="chip ${g.color}" id="chip"><div class="bar"></div><div><div class="main">${esc(text)} <span class="muted">${swingTxt}</span></div><div class="sub"><b>${verdict}</b> ${better}</div></div></div>`;
  }
  onGrade(d: Decision): void {
    track("call", { call: labelOf(d.action), grade: d.grade?.color, gap: Math.round(1000 * (d.grade?.gap ?? 0)) / 10 });
    const last = this.sess?.decisions[this.sess.decisions.length - 1];
    if (d === last) document.getElementById("chip")?.replaceWith(el(this.chipHtml(d)));
    this.persist();
  }
  onGradeProgress(d: Decision, done: number, total: number): void {
    const last = this.sess?.decisions[this.sess.decisions.length - 1];
    if (d === last) { const p = document.getElementById("chip-prog"); if (p) p.textContent = `${Math.round((100 * done) / total)}%`; }
  }

  async play(action: Action): Promise<void> {
    if (!this.sess || this.busy || this.sess.state.phase === DONE) return;
    this.busy = true;
    if (this.sess.decisions.length === 0) track("drive_start", { spot: this.sess.spot.id, cat: this.sess.spot.cat });
    const sceneBefore = this.scene();
    if (action.type === "look") this.lastLook = { box: action.box, blitz: action.blitz };
    const d = this.sess.act(action);
    this.persist();
    // animate the snap (plays only), then redraw
    const playEv = d.events.find((e) => e.kind === "play");
    if (playEv && this.field) {
      this.skip = { skip: false };
      this.field.render(sceneBefore, null);
      const callout = document.getElementById("callout")!;
      const show = (t: string) => { callout.textContent = t; callout.classList.add("show"); setTimeout(() => callout.classList.remove("show"), 1400); };
      const hintRow = this.hintsFor(playEv);
      document.getElementById("field")!.addEventListener("click", () => { this.skip.skip = true; }, { once: true });
      await animatePlay(this.field, sceneBefore, playEv, hintRow, show, this.skip);
      await new Promise((r) => setTimeout(r, 350));
    }
    this.busy = false;
    this.ds.tempo = this.sess.defaultTempo();
    this.drawPlayScreen();
    if (this.sess.announce) { this.toast(this.sess.announce); this.sess.announce = null; }
    if (isDone(this.sess.state)) this.toast("Final whistle. See the result below.");
  }
  hintsFor(e: import("@engine/engine").Event): Hints {
    const h = this.deps.hints, i = e.row;
    const pb = this.deps.data.playbook.cols;
    const call = e.call;
    const isRun = call.startsWith("run") || call === "qb_sneak";
    const dir = call.endsWith("left") ? "left" : call.endsWith("right") ? "right" : "middle";
    const depth = call.includes("deep") ? "deep" : call.includes("medium") ? "medium" : "short";
    return { air: i >= 0 ? pb.air[i] : -99, yac: h && i >= 0 ? h.yac[i] : -99, ttt: h && i >= 0 ? h.ttt10[i] / 10 : -1, dir, depth, isPass: !isRun, isRun,
      sack: i >= 0 && pb.sack[i] === 1, inc: i >= 0 && pb.inc[i] === 1, to: i >= 0 ? pb.to[i] : 0, scramble: h && i >= 0 ? h.scr[i] === 1 : false, yards: e.yards, oob: i >= 0 && pb.oob[i] === 1 };
  }

  persist(): void {
    const sess = this.sess;
    if (!sess || this.route.view !== "play") return;
    const mode = (this.route as { mode: "daily" | "survivor" }).mode;
    const save: DriveSave = { spotId: sess.spot.id, status: sess.status, seed: sess.seed, actions: sess.decisions.map((d) => d.action), grades: [], startedAt: Date.now() };
    if (sess.summary) { save.percentile = sess.summary.percentile; save.result = sess.summary.resultText; save.coach = sess.summary.coach ?? undefined; }
    update((st) => {
      if (mode === "daily") { const t = todayKey(); st.progress[t] = st.progress[t] ?? {}; st.progress[t][sess.spot.id] = save; }
      else if (st.survivor.run) st.survivor.run.current = save;
    });
  }

  // ---- end card
  async finish(): Promise<void> {
    const sess = this.sess!;
    if (sess.gradesPending) { this.toast("Finishing the grades…"); await new Promise<void>((res) => { const t = setInterval(() => { if (!sess.gradesPending) { clearInterval(t); res(); } }, 200); }); }
    const sum = sess.finish();
    const mode = (this.route as { mode: "daily" | "survivor" }).mode;
    const { scored } = todaysSpots(this.deps.game);
    const isScored = mode === "daily" && sess.spot.cat === scored;
    const store = loadStore();
    const already = store.progress[todayKey()]?.[sess.spot.id]?.percentile !== undefined;
    if (!already) update((st) => {
      if (isScored) {
        st.stats.played += 1;
        const t = todayKey();
        const yesterday = new Date(); yesterday.setDate(yesterday.getDate() - 1);
        const yk = todayKey(yesterday);
        st.stats.streak = st.stats.lastDay === yk || st.stats.lastDay === t ? st.stats.streak + (st.stats.lastDay === t ? 0 : 1) : 1;
        st.stats.lastDay = t;
        st.stats.best = Math.max(st.stats.best, sum.percentile);
        st.stats.hist[Math.min(9, Math.floor(sum.percentile / 10))] += 1;
        st.stats.wlt[sum.vsCoach === "W" ? 0 : sum.vsCoach === "L" ? 1 : 2] += 1;
      }
      if (mode === "survivor" && st.survivor.run) {
        const won = sum.mine === 1, tie = sum.mine === 0.5;
        if (won) st.survivor.run.wins += 1;
        if (!won && !tie) st.survivor.run.alive = false;
        st.survivor.best = Math.max(st.survivor.best, st.survivor.run.wins);
        st.survivor.run.index += 1;
        st.survivor.run.current = undefined;
      }
    });
    if (mode === "daily") this.persist();
    const st2 = loadStore();
    const squares = sum.squares.map((c) => (c === "green" ? "🟩" : c === "yellow" ? "🟨" : c === "red" ? "🟥" : "⬜"));
    const grouped = squares.length > 8 ? squares.slice(0, 8) : squares;
    const share = `${this.deps.game.name} #${todaysSpots(this.deps.game).day + 1} · ${ordinal(Math.round(sum.percentile))} pct\n${grouped.join("")}  ${sum.vsCoach === "W" ? "Beat the coach" : sum.vsCoach === "T" ? "Matched the coach" : "Coach wins"}\n${location.origin}${location.pathname}`;
    const costl = sum.costliest.filter((c) => c.gap >= 0.01).map((c) => `<div>#${c.idx + 1} ${esc(c.call)}: −${(100 * c.gap).toFixed(1)}%${c.better ? ` (better: ${esc(c.better.replace(/_/g, " "))})` : ""}</div>`).join("") || "<div class='muted'>No costly calls. Nice.</div>";
    this.root.innerHTML = this.header(mode === "survivor" ? "Survivor" : isScored ? "Today's scored drive" : "Practice drive") + `
      <div class="card" style="text-align:center"><div class="muted">Percentile vs simulated play-callers</div><div class="big">${Math.round(sum.percentile)}<small>${ordinal(Math.round(sum.percentile)).replace(/\d+/, "")}</small></div>
        <div style="margin:8px 0 2px">${sum.resultText} · vs the real coach: <b>${sum.vsCoach === "W" ? "Win" : sum.vsCoach === "L" ? "Loss" : "Tie"}</b> (real: ${sess.spot.state.qtr === 2 ? `${sum.real >= 0 ? "+" : ""}${sum.real}` : sess.spot.real.outcome})</div>
        <div class="squares">${squares.join("")}</div>
        <p>You coached like <b>${esc(sum.coach ?? "nobody in particular")}</b>${sum.reasons.length ? `: you ${esc(sum.reasons.join(", "))}.` : "."}</p>
        <div class="row"><button class="primary grow" data-share="${esc(share)}">Share</button><button class="grow" data-go="${mode === "survivor" ? "survivor" : "daily"}">${mode === "survivor" && st2.survivor.run?.alive ? "Next spot" : "Home"}</button></div></div>
      <div class="card"><h3>Costliest calls</h3>${costl}</div>
      <div class="card"><div class="stat"><div><b>${st2.stats.streak}</b><span>Day streak</span></div><div><b>${st2.stats.wlt.join("-")}</b><span>W-L-T vs real coaches</span></div></div>
        <p class="muted" style="margin-bottom:0">Today's global rank: <span id="rank">…</span></p></div>
      <div class="ad">Ad</div>` + this.footer();
    this.sess = null;
    track("drive_end", { percentile: Math.round(sum.percentile), result: sum.vsCoach, mode });
    const rankEl = document.getElementById("rank");
    const r = isScored ? await postDaily({ date: todayKey(), key: st2.key, name: st2.name || undefined, score: sum.percentile, spots: [sess.spot.id] })
      : mode === "survivor" && !st2.survivor.run?.alive ? await postBoard({ name: st2.name || "anon", key: st2.key, best: st2.survivor.best }).then(() => null) : null;
    if (rankEl) rankEl.textContent = r ? `${ordinal(r.rank)} of ${r.n} today` : isScored ? "unavailable offline" : "practice drives are not ranked";
  }

  // ---- modals
  openModal(kind: string): void {
    const store = loadStore();
    let body = "";
    if (kind === "help") body = `<h2>How to play</h2><p>1. You get one real late-game drive. 2. Call the play: run, pass depth and side, or a situational move. 3. Every call is graded by win probability against thousands of simulated endings: green is best, yellow is close, red costs you.</p>
      <p>Pre-snap, your tempo decides how much clock you burn. Inside two minutes, incompletions and sideline catches stop the clock. On defense you pick the look. At the end you get a percentile against simulated play-callers and a verdict against the real coach.</p>`;
    else if (kind === "stats") body = `<h2>Stats</h2><div class="stat"><div><b>${store.stats.played}</b><span>Scored drives</span></div><div><b>${store.stats.streak}</b><span>Streak</span></div><div><b>${Math.round(store.stats.best)}</b><span>Best percentile</span></div><div><b>${store.stats.wlt.join("-")}</b><span>vs real coaches</span></div></div>
      <h3 style="margin-top:12px">Percentile histogram</h3><div class="pbp">${store.stats.hist.map((n, i) => `<div>${i * 10}–${i * 10 + 9}: ${"▮".repeat(n)}${n ? ` ${n}` : ""}</div>`).join("")}</div>`;
    else if (kind === "ratings" && this.file) {
      const side = (p: { team: string; players: { name: string; pos: string; rating: number }[] }) => `<h3>${esc(p.team)}</h3><div class="ratings-list">${p.players.slice().sort((a, b) => b.rating - a.rating).map((x) => `<div><span>${esc(x.pos)} ${esc(x.name)}</span><b style="color:${ratingColor(x.rating)}">${x.rating}</b></div>`).join("")}</div>`;
      body = `<h2>Player ratings</h2><p class="muted">Our own 40–99 scale from nflverse stats: 77 is a typical starter.</p>${side(this.file.off)}${side(this.file.def)}`;
    } else if (kind === "privacy") body = `<h2>Privacy</h2><p>Progress, stats and a random device key live in your browser's localStorage. No account. If a leaderboard is enabled, the name you enter and your scores are sent to it. Analytics and ads, if present, use cookies per their own policies.</p>`;
    else if (kind === "terms") body = `<h2>Terms</h2><p>A fan-made game for entertainment. ${esc(this.deps.game.disclaimer)} Provided as is, no warranty.</p>`;
    const m = el(`<div class="modal"><div class="sheet">${body}<button class="primary" style="width:100%;margin-top:12px" data-close="1">Close</button></div></div>`);
    m.addEventListener("click", (e) => { if ((e.target as HTMLElement).dataset.close || e.target === m) m.remove(); });
    document.body.appendChild(m);
  }

  // ---- clicks
  onClick(e: MouseEvent): void {
    const t = (e.target as HTMLElement).closest("[data-act],[data-go],[data-modal],[data-mode],[data-depth],[data-tempo],[data-finish],[data-share],[data-survivor]") as HTMLElement | null;
    if (!t) return;
    const d = t.dataset;
    if (d.modal) { e.preventDefault(); this.openModal(d.modal); return; }
    if (d.go) { this.go(d.go); return; }
    if (d.mode) { this.ds.mode = d.mode as DockState["mode"]; this.drawPlayScreen(); return; }
    if (d.depth) { this.ds.depth = d.depth as DockState["depth"]; this.drawPlayScreen(); return; }
    if (d.tempo) { this.ds.tempo = d.tempo; this.drawPlayScreen(); return; }
    if (d.act) { void this.play(JSON.parse(d.act) as Action); return; }
    if (d.finish) { void this.finish(); return; }
    if (d.share) { void this.share(d.share); return; }
    if (d.survivor) { this.startSurvivor(d.survivor === "new"); return; }
  }
  async share(text: string): Promise<void> {
    try {
      if (navigator.share) await navigator.share({ text });
      else { await navigator.clipboard.writeText(text); this.toast("Copied to clipboard"); }
    } catch { this.toast("Could not share"); }
  }
  startSurvivor(fresh: boolean): void {
    const store = loadStore();
    if (fresh || !store.survivor.run) update((st) => { st.survivor.run = { seed: (Math.random() * 4294967296) >>> 0, index: 0, wins: 0, alive: true }; });
    const run = loadStore().survivor.run!;
    const order = survivorOrder(this.deps.game, run.seed);
    const id = order[run.index % order.length];
    this.sess = null;
    this.go(`survivor/spot/${id}`);
  }
}
