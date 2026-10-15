/** Compare the TS engine against Python fixtures: npm run parity */
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { Engine } from "./engine";
import { grade } from "./grading";
import { loadGameNode, loadNode } from "./load-node";
import { Policy } from "./policy";
import { Rng } from "./rng";
import { playOut, stateFromSpot } from "./simulate";

const fx = JSON.parse(readFileSync(fileURLToPath(new URL("./fixtures/parity.json", import.meta.url)), "utf8"));
const data = loadNode();
const game = loadGameNode();
const byId = new Map(game.spots.map((s) => [s.id, s]));

// RNG
const r = new Rng(12345);
const seq = [r.next(), r.next(), r.next(), r.next(), r.next(), new Rng(0).next(), new Rng(0xffffffff).next()];
const rngOk = seq.every((v, i) => v === fx.rng[i]);
console.log("rng identical:", rngOk);

let same = 0, sameScore = 0, total = 0, firstDiff: string | null = null;
const t0 = Date.now();
for (const g of fx.games) {
  const spot = byId.get(g.spot)!;
  const [s, ctx] = stateFromSpot(spot);
  const eng = new Engine(data, ctx);
  const log: import("./engine").Event[] = [];
  const v = playOut(eng, s, new Rng(g.seed), [new Policy(data), new Policy(data)], log);
  total += 1;
  const evs = log.map((e) => [e.kind, e.text, e.yards, e.score[0], e.score[1], e.presnap, e.duration]);
  const identical = JSON.stringify(evs) === JSON.stringify(g.events) && Math.abs(v - g.value) < 1e-9 && s.score[0] === g.score[0] && s.score[1] === g.score[1];
  if (identical) same += 1;
  if (s.score[0] === g.score[0] && s.score[1] === g.score[1]) sameScore += 1;
  if (!identical && !firstDiff) {
    let k = 0;
    while (k < evs.length && k < g.events.length && JSON.stringify(evs[k]) === JSON.stringify(g.events[k])) k++;
    firstDiff = `${g.spot} seed ${g.seed}: first difference at event ${k}\n  py: ${JSON.stringify(g.events[k])}\n  ts: ${JSON.stringify(evs[k])}`;
  }
}
const dt = Date.now() - t0;
console.log(`games identical: ${same}/${total} (same final score ${sameScore}/${total}), ${(dt / total).toFixed(2)} ms/game`);
if (firstDiff) console.log(firstDiff);

// grade
const gs = byId.get(fx.grade.spot)!;
const [s0, ctx] = stateFromSpot(gs);
const eng = new Engine(data, ctx);
const tg = Date.now();
const gr = grade(eng, s0, { type: "play", call: fx.grade.chosen, tempo: "hurry" }, fx.grade.seed, { n1: fx.grade.n1, n2: fx.grade.n2 });
let optOk = 0;
for (let i = 0; i < gr.options.length; i++) {
  const o = gr.options[i], p = fx.grade.options[i];
  if (p && o.label === p.label && Math.abs(o.wp1 - p.wp1) < 1e-9 && ((o.wp2 === null && p.wp2 === null) || Math.abs((o.wp2 ?? 0) - (p.wp2 ?? 0)) < 1e-9) && Math.abs(o.q - p.q) < 1e-9) optOk += 1;
  else if (p) console.log("  option differs:", o.label, o.wp1, p.wp1, o.wp2, p.wp2, o.q, p.q);
}
console.log(`grade options identical: ${optOk}/${gr.options.length}; best ${gr.options[gr.best].label} vs ${fx.grade.best}; gap ${gr.gap.toFixed(6)} vs ${fx.grade.gap.toFixed(6)}; ${Date.now() - tg} ms at n1=${fx.grade.n1}, n2=${fx.grade.n2}`);
if (!rngOk || same !== total || optOk !== gr.options.length) process.exit(1);
