/** v1 motion: scripted keyframes with eased tweens (teleport-free, but no physics yet). */
import type { Event } from "@engine/engine";
import { FieldView, W, type Scene } from "../field/field";

interface Key { t: number; x: number; L: number }
interface Track { id: string; keys: Key[] }
const reduced = () => typeof matchMedia !== "undefined" && matchMedia("(prefers-reduced-motion: reduce)").matches;
const ease = (u: number) => (u < 0.5 ? 2 * u * u : 1 - Math.pow(-2 * u + 2, 2) / 2);
const lerp = (a: number, b: number, u: number) => a + (b - a) * u;

function posAt(keys: Key[], t: number): [number, number] {
  if (t <= keys[0].t) return [keys[0].x, keys[0].L];
  for (let i = 1; i < keys.length; i++) {
    if (t <= keys[i].t) {
      const a = keys[i - 1], b = keys[i];
      const u = ease((t - a.t) / Math.max(1e-6, b.t - a.t));
      return [lerp(a.x, b.x, u), lerp(a.L, b.L, u)];
    }
  }
  const k = keys[keys.length - 1];
  return [k.x, k.L];
}

export interface Hints { air: number; yac: number; ttt: number; dir: string; depth: string; isPass: boolean; isRun: boolean; sack: boolean; inc: boolean; to: number; scramble: boolean; yards: number; oob: boolean }

/** Build and play the play's animation. Resolves when done or skipped. */
export function animatePlay(view: FieldView, scene: Scene, ev: Event, h: Hints, callout: (text: string) => void, skipSignal: { skip: boolean }): Promise<void> {
  const dir = scene.dir;
  const los = scene.los;
  const endL = los + dir * ev.yards;
  const cx = W / 2;
  const off = scene.dots.filter((d) => (dir === 1 ? d.side === 0 : d.side === 1));
  const def = scene.dots.filter((d) => (dir === 1 ? d.side === 1 : d.side === 0));
  const qb = off.find((d) => d.grp === "QB"), rb = off.find((d) => d.grp === "RB");
  const dx = h.dir === "left" ? -14 : h.dir === "right" ? 14 : 0;
  const tracks: Track[] = [];
  let ballKeys: (Key & { h: number })[] = [];
  let total = 3.2;
  const snapT = 0.25;
  const push = (id: string, keys: Key[]) => tracks.push({ id, keys });
  const dot = (d: { x: number; L: number }) => ({ x: d.x, L: d.L });

  if (h.isPass && qb && !h.scramble) {
    const ttt = Math.max(1.2, Math.min(4.5, h.ttt > 0 ? h.ttt : 2.6));
    const air = h.air > -99 ? h.air : Math.max(2, Math.min(15, ev.yards));
    const catchL = los + dir * air;
    const catchX = Math.max(3, Math.min(W - 3, cx + dx + (h.dir === "middle" ? 0 : 0)));
    const flight = Math.max(0.5, Math.hypot(air, dx) / 24);
    const catchT = snapT + ttt + flight;
    const target = off.filter((d) => d.grp === "WR" || d.grp === "TE" || d.grp === "RB").sort((a, b) => Math.abs(a.x - catchX) - Math.abs(b.x - catchX))[0];
    push(qb.id, [{ t: 0, ...dot(qb) }, { t: snapT + 0.9, x: qb.x, L: qb.L - dir * 5 }, { t: total, x: qb.x, L: qb.L - dir * 5 }]);
    if (h.sack) {
      const rusher = def.filter((d) => d.grp === "DL")[0];
      total = snapT + ttt + 0.6;
      if (rusher) push(rusher.id, [{ t: 0, ...dot(rusher) }, { t: snapT + ttt, x: qb.x, L: qb.L - dir * 5 }]);
      push(qb.id, [{ t: 0, ...dot(qb) }, { t: snapT + 0.9, x: qb.x, L: qb.L - dir * 5 }, { t: snapT + ttt, x: qb.x, L: endL }]);
      ballKeys = [{ t: 0, x: qb.x, L: qb.L, h: 0 }, { t: snapT + ttt, x: qb.x, L: endL, h: 0 }];
      setTimeout(() => callout("Sacked!"), (snapT + ttt) * 1000);
    } else if (target) {
      const finalL = h.inc ? catchL : endL;
      const finalX = h.inc ? catchX : Math.max(2, Math.min(W - 2, catchX + (h.oob ? (catchX < cx ? -catchX + 0.5 : W - catchX - 0.5) : (Math.random() - 0.5) * 6)));
      const yacT = h.inc ? 0 : Math.max(0.3, Math.abs(ev.yards - air) / 9);
      total = catchT + yacT + 0.5;
      push(target.id, [{ t: 0, ...dot(target) }, { t: snapT + 0.2, ...dot(target) }, { t: catchT, x: catchX, L: catchL }, { t: catchT + yacT, x: finalX, L: finalL }]);
      ballKeys = [{ t: 0, x: qb.x, L: qb.L, h: 0 }, { t: snapT + ttt, x: qb.x, L: qb.L - dir * 5, h: 0 }, { t: snapT + ttt + flight / 2, x: (qb.x + catchX) / 2, L: (qb.L - dir * 5 + catchL) / 2, h: Math.min(30, 6 + air) },
        { t: catchT, x: catchX, L: catchL, h: 0 }, { t: catchT + yacT, x: finalX, L: finalL, h: 0 }];
      // nearest defender closes; for an incompletion he arrives on time
      const nearest = def.filter((d) => d.grp === "DB" || d.grp === "LB").sort((a, b) => Math.hypot(a.x - catchX, a.L - catchL) - Math.hypot(b.x - catchX, b.L - catchL))[0];
      if (nearest) push(nearest.id, [{ t: 0, ...dot(nearest) }, { t: snapT + 0.3, ...dot(nearest) }, { t: catchT + (h.inc ? 0 : 0.25), x: catchX + (h.inc ? 0.8 : 2), L: catchL + (h.inc ? 0.5 : 1.5) }, { t: catchT + yacT, x: finalX + 0.6, L: finalL + dir * 0.6 }]);
      // other receivers run routes
      off.filter((d) => d !== target && (d.grp === "WR" || d.grp === "TE")).forEach((d, i) => push(d.id, [{ t: 0, ...dot(d) }, { t: snapT + 0.2, ...dot(d) }, { t: catchT, x: d.x + (i % 2 ? 3 : -3), L: d.L + dir * (8 + 4 * i) }]));
      if (h.inc) setTimeout(() => callout(h.to === 2 ? "Intercepted!" : "Incomplete"), catchT * 1000);
      else if (ev.td) setTimeout(() => callout("Touchdown!"), (catchT + yacT) * 1000);
    }
  } else if (qb) {
    // run (or scramble): the carrier takes the handoff and follows the direction
    const carrier = h.scramble ? qb : (rb ?? qb);
    const meshT = snapT + 0.6;
    const runT = Math.max(0.6, Math.abs(ev.yards) / 7 + 0.4);
    const finalX = Math.max(2, Math.min(W - 2, cx + dx * 0.6 + (h.oob ? (dx < 0 ? -20 : 20) : 0)));
    total = meshT + runT + 0.5;
    if (!h.scramble && rb) push(qb.id, [{ t: 0, ...dot(qb) }, { t: meshT, x: qb.x, L: qb.L - dir * 1.5 }, { t: total, x: qb.x, L: qb.L - dir * 1.5 }]);
    push(carrier.id, [{ t: 0, ...dot(carrier) }, { t: meshT, x: carrier.x + (dx ? Math.sign(dx) * 2 : 0), L: los - dir * 1 }, { t: meshT + runT, x: finalX, L: endL }]);
    ballKeys = [{ t: 0, x: qb.x, L: qb.L, h: 0 }, { t: meshT, x: carrier.x, L: los - dir, h: 0 }, { t: meshT + runT, x: finalX, L: endL, h: 0 }];
    const tackler = def.sort((a, b) => Math.hypot(a.x - finalX, a.L - endL) - Math.hypot(b.x - finalX, b.L - endL))[0];
    if (tackler && !ev.td) push(tackler.id, [{ t: 0, ...dot(tackler) }, { t: snapT + 0.3, ...dot(tackler) }, { t: meshT + runT, x: finalX + 0.7, L: endL + dir * 0.7 }]);
    if (ev.td) setTimeout(() => callout("Touchdown!"), (meshT + runT) * 1000);
    else if (h.to === 1) setTimeout(() => callout("Fumble!"), (meshT + runT) * 1000);
  }
  // linemen: a little surge
  off.filter((d) => d.grp === "OL").forEach((d) => push(d.id, [{ t: 0, ...dot(d) }, { t: snapT + 0.8, x: d.x, L: d.L - dir * (h.isPass ? 1.5 : -0.8) }]));
  def.filter((d) => d.grp === "DL").forEach((d) => push(d.id, [{ t: 0, ...dot(d) }, { t: snapT + 0.9, x: d.x, L: d.L - dir * (h.isPass ? 2.2 : 0.6) }]));

  if (reduced()) {
    for (const tr of tracks) { const k = tr.keys[tr.keys.length - 1]; view.moveDot(tr.id, k.x, k.L); }
    return Promise.resolve();
  }
  view.frame(los, dir, true);
  return new Promise((resolve) => {
    const t0 = performance.now();
    const tick = () => {
      const t = Math.min(total, (performance.now() - t0) / 1000);
      for (const tr of tracks) { const [x, L] = posAt(tr.keys, t); view.moveDot(tr.id, x, L); }
      if (ballKeys.length) {
        const [x, L] = posAt(ballKeys, t);
        let hh = 0;
        for (let i = 1; i < ballKeys.length; i++) if (t <= ballKeys[i].t) { const a = ballKeys[i - 1], b = ballKeys[i]; const u = (t - a.t) / Math.max(1e-6, b.t - a.t); hh = lerp(a.h, b.h, u); break; }
        view.ball(x, L, hh);
      }
      if (t >= total || skipSignal.skip) {
        for (const tr of tracks) { const k = tr.keys[tr.keys.length - 1]; view.moveDot(tr.id, k.x, k.L); }
        resolve();
      } else requestAnimationFrame(tick);
    };
    requestAnimationFrame(tick);
  });
}
