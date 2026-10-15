/** SVG field in yards: x 0..53.3 across, L = yards from the player's goal line (0) to the opponent's (100).
 * The player's end zone is at the bottom (SVG y = 110 - L). */
import type { State } from "@engine/engine";
import type { Player } from "../data";
import { ratingColor } from "../util";

export const W = 53.3;
export interface Dot { id: string; x: number; L: number; r: number; name: string; grp: string; side: 0 | 1; num: number | null; rating: number; tag: string }
export interface Scene { los: number; dir: 1 | -1; dots: Dot[]; routes: { id: string; pts: [number, number][] }[] }

const PICK = (ps: Player[], grp: string, n: number) => ps.filter((p) => p.grp === grp).slice(0, n);

/** Build pre-snap positions. `me` = the player's lineup (side 0), `them` = the opponent's (side 1). */
export function formation(state: State, mine: Player[], theirs: Player[], look: { box: "light" | "heavy"; blitz: boolean } | null, shotgun: boolean): Scene {
  const meOnOffense = state.poss === 0;
  const los = meOnOffense ? 100 - state.yl : state.yl;
  const dir: 1 | -1 = meOnOffense ? 1 : -1;
  const off = meOnOffense ? mine : theirs, def = meOnOffense ? theirs : mine;
  const offSide: 0 | 1 = meOnOffense ? 0 : 1, defSide: 0 | 1 = meOnOffense ? 1 : 0;
  const cx = W / 2;
  const dots: Dot[] = [];
  const put = (p: Player, dx: number, dL: number, side: 0 | 1, tag: string) =>
    dots.push({ id: p.id, x: cx + dx, L: los + dL * dir, r: side === offSide ? 0.9 : 0.9, name: p.name, grp: p.grp, side, num: p.num, rating: p.rating, tag });
  // offense
  const ol = PICK(off, "OL", 5), qb = PICK(off, "QB", 1), rb = PICK(off, "RB", 2), te = PICK(off, "TE", 3), wr = PICK(off, "WR", 5);
  ol.forEach((p, i) => put(p, (i - 2) * 1.7, -0.8, offSide, ""));
  const skill = [...wr, ...te.slice(1), ...rb.slice(1)];
  if (qb[0]) put(qb[0], 0, shotgun ? -5 : -1.4, offSide, "QB");
  if (rb[0]) put(rb[0], shotgun ? -3.2 : 0, shotgun ? -5.6 : -7.5, offSide, "RB");
  if (te[0]) put(te[0], 5.2, -0.8, offSide, "TE");
  const wrSpots: [number, number][] = [[-21, -0.8], [21, -1.6], [-13, -1.4], [15, -1.0], [-8, -1.2]];
  skill.slice(0, 5).forEach((p, i) => put(p, wrSpots[i][0], wrSpots[i][1], offSide, p.grp === "WR" ? `WR${i + 1}` : p.grp));
  // defense
  const dl = PICK(def, "DL", 4), lb = PICK(def, "LB", 3), db = PICK(def, "DB", 5);
  const heavy = look?.box === "heavy", blitz = look?.blitz ?? false;
  dl.forEach((p, i) => put(p, [-3.4, -1.2, 1.2, 3.4][i] ?? 0, 1.4, defSide, ""));
  lb.forEach((p, i) => put(p, [-4.5, 0.5, 4.5][i] ?? 0, blitz && i < 2 ? 1.6 : 4.5, defSide, "LB"));
  const dbSpots: [number, number][] = [[-20, 6], [20, 6], [-12, 7.5], [heavy ? 7 : -7, heavy ? 5.5 : 12], [7, 12]];
  db.forEach((p, i) => put(p, dbSpots[i][0], dbSpots[i][1], defSide, i < 3 ? "CB" : "S"));
  return { los, dir, dots, routes: [] };
}

export class FieldView {
  svg: SVGSVGElement;
  gDots: SVGGElement;
  gRoutes: SVGGElement;
  gBall: SVGGElement;
  private viewTarget: [number, number, number, number] = [0, 0, W, 120];
  constructor(public root: HTMLElement) {
    root.innerHTML = `<svg viewBox="0 0 ${W} 120" preserveAspectRatio="xMidYMid meet" aria-label="Field"></svg>`;
    this.svg = root.querySelector("svg")!;
    this.svg.innerHTML = this.fieldMarkup();
    this.gRoutes = this.g("routes");
    this.gDots = this.g("dots");
    this.gBall = this.g("ball");
  }
  private g(id: string): SVGGElement { const g = document.createElementNS("http://www.w3.org/2000/svg", "g"); g.id = id; this.svg.appendChild(g); return g; }
  private fieldMarkup(): string {
    let s = `<rect x="0" y="0" width="${W}" height="120" fill="var(--field)"/>`;
    s += `<rect x="0" y="0" width="${W}" height="10" fill="var(--endzone)"/><rect x="0" y="110" width="${W}" height="10" fill="var(--endzone)"/>`;
    for (let L = 0; L <= 100; L += 5) {
      const y = 110 - L;
      s += `<line x1="0" x2="${W}" y1="${y}" y2="${y}" stroke="var(--field-line)" stroke-width="${L % 10 === 0 ? 0.25 : 0.12}"/>`;
      if (L % 10 === 0 && L > 0 && L < 100) {
        const n = L <= 50 ? L : 100 - L;
        s += `<text x="3" y="${y + 1.2}" font-size="3.2" fill="rgba(255,255,255,.35)" font-family="var(--display)">${n}</text><text x="${W - 3}" y="${y + 1.2}" font-size="3.2" fill="rgba(255,255,255,.35)" text-anchor="end" font-family="var(--display)">${n}</text>`;
      }
    }
    for (let L = 1; L < 100; L++) if (L % 5) { const y = 110 - L; s += `<line x1="18" x2="19" y1="${y}" y2="${y}" stroke="var(--field-line)" stroke-width=".1"/><line x1="${W - 19}" x2="${W - 18}" y1="${y}" y2="${y}" stroke="var(--field-line)" stroke-width=".1"/>`; }
    s += `<line id="los" x1="0" x2="${W}" y1="35" y2="35" stroke="#4cc9f0" stroke-width=".35"/><line id="fd" x1="0" x2="${W}" y1="25" y2="25" stroke="#ffb703" stroke-width=".35"/>`;
    return s;
  }
  static y(L: number): number { return 110 - L; }

  render(scene: Scene, firstDownL: number | null): void {
    (this.svg.querySelector("#los") as SVGLineElement).setAttribute("y1", String(FieldView.y(scene.los)));
    (this.svg.querySelector("#los") as SVGLineElement).setAttribute("y2", String(FieldView.y(scene.los)));
    const fd = this.svg.querySelector("#fd") as SVGLineElement;
    fd.style.display = firstDownL === null ? "none" : "";
    if (firstDownL !== null) { fd.setAttribute("y1", String(FieldView.y(firstDownL))); fd.setAttribute("y2", String(FieldView.y(firstDownL))); }
    this.gDots.innerHTML = scene.dots.map((d) => {
      const y = FieldView.y(d.L);
      const tag = d.tag && d.grp !== "OL" && d.grp !== "DL" ? `<text x="${d.x}" y="${y - 1.5}" font-size="2" text-anchor="middle" fill="#fff" font-family="var(--display)" opacity=".85">${(d.name.split(" ").pop() ?? "").slice(0, 10)}</text>` : "";
      const num = d.num !== null ? `<text x="${d.x}" y="${y + 0.55}" font-size="1.5" text-anchor="middle" fill="#000" font-weight="700" font-family="var(--display)">${d.num}</text>` : "";
      return `<g class="dot" data-id="${d.id}" transform="translate(0,0)"><circle cx="${d.x}" cy="${y}" r="${d.r}" fill="${ratingColor(d.rating)}" stroke="${d.side === 0 ? "#fff" : "#000"}" stroke-width=".18"/>${num}${tag}<circle cx="${d.x}" cy="${y}" r="2.6" fill="transparent" class="hit"/></g>`;
    }).join("");
    this.gRoutes.innerHTML = scene.routes.map((r) => `<polyline points="${r.pts.map(([x, L]) => `${x},${FieldView.y(L)}`).join(" ")}" fill="none" stroke="#ffb703" stroke-width=".3" stroke-dasharray="1 .6"/>`).join("");
    this.gBall.innerHTML = "";
    this.frame(scene.los, scene.dir, false);
  }
  /** Camera: whole field pre-snap zoomed loosely around the ball. */
  frame(los: number, dir: 1 | -1, tight: boolean): void {
    const span = tight ? 34 : 46;
    const center = los + dir * (tight ? 8 : 6);
    let top = FieldView.y(center) - span / 2;
    top = Math.max(0, Math.min(120 - span, top));
    this.viewTarget = [0, top, W, span];
    this.svg.setAttribute("viewBox", this.viewTarget.join(" "));
  }
  moveDot(id: string, x: number, L: number): void {
    const g = this.gDots.querySelector(`[data-id="${id}"]`) as SVGGElement | null;
    if (!g) return;
    const c = g.querySelector("circle")!;
    const x0 = Number(c.getAttribute("cx")), y0 = Number(c.getAttribute("cy"));
    g.setAttribute("transform", `translate(${x - x0},${FieldView.y(L) - y0})`);
  }
  ball(x: number | null, L: number, h = 0): void {
    if (x === null) { this.gBall.innerHTML = ""; return; }
    const y = FieldView.y(L);
    const sc = 1 + Math.min(0.35, h / 40);
    this.gBall.innerHTML = `<ellipse cx="${x + h / 12}" cy="${y + h / 10}" rx="${0.55}" ry="${0.35}" fill="rgba(0,0,0,.35)"/><ellipse cx="${x}" cy="${y}" rx="${0.55 * sc}" ry="${0.38 * sc}" fill="#c9742a" stroke="#fff" stroke-width=".08"/>`;
  }
}
