/** The call dock: offense, defense, PAT, and kickoff controls. */
import type { Action } from "@engine/engine";
import type { Session } from "../session";

export interface DockState { mode: "run" | "pass" | "pa" | "other"; depth: "short" | "medium" | "deep"; tempo: string }

const DIRS = [["left", "L"], ["middle", "M"], ["right", "R"]] as const;

export function renderDock(sess: Session, ds: DockState, pick: (a: Action) => void, setDs: (p: Partial<DockState>) => void): string {
  const s = sess.state;
  const turn = sess.turn();
  if (turn === "none") return `<div class="dock"><div class="muted">Waiting on the other side...</div></div>`;
  if (turn === "pat") return `<div class="dock"><div class="lbl">After the touchdown</div><div class="grid2"><button data-act='{"type":"xp"}'>Extra point<span class="hint">~94%</span></button><button data-act='{"type":"two_pt"}'>Go for two<span class="hint">~48%</span></button></div></div>`;
  if (turn === "kickoff") return `<div class="dock"><div class="lbl">Kickoff</div><div class="grid2"><button data-act='{"type":"kickoff"}'>Kick deep</button><button data-act='{"type":"onside"}'>Onside kick<span class="hint">~8% recovery</span></button></div></div>`;
  if (turn === "defense") {
    const to = s.running && s.tos[0] > 0 ? `<div class="sit"><button data-act='{"type":"timeout","team":0}'>Timeout (${s.tos[0]} left)</button></div>` : "";
    return `<div class="dock"><div class="lbl">Defense: pick your look</div><div class="grid2">
      <button data-act='{"type":"look","box":"light","blitz":false}'>Light box<span class="hint">6 or fewer, 4 rushers</span></button>
      <button data-act='{"type":"look","box":"heavy","blitz":false}'>Loaded box<span class="hint">7+, 4 rushers</span></button>
      <button data-act='{"type":"look","box":"light","blitz":true}'>Light box, blitz<span class="hint">5+ rushers</span></button>
      <button data-act='{"type":"look","box":"heavy","blitz":true}'>Loaded box, blitz<span class="hint">sell out</span></button></div>${to}</div>`;
  }
  // offense
  const tabs = [["run", "Run"], ["pass", "Pass"], ["pa", "Play action"], ["other", "RPO / Screen"]] as const;
  let body = "";
  const play = (call: string) => JSON.stringify({ type: "play", call, tempo: ds.tempo });
  if (ds.mode === "run") {
    body = `<div class="lbl">Inside</div><div class="grid3">${DIRS.map(([d, l]) => `<button data-act='${play(`run_inside_${d}`)}'>${l}</button>`).join("")}</div>
      <div class="lbl">Outside</div><div class="grid2"><button data-act='${play("run_outside_left")}'>Left</button><button data-act='${play("run_outside_right")}'>Right</button></div>
      ${s.togo <= 2 || s.yl <= 2 ? `<div class="sit"><button data-act='${play("qb_sneak")}'>QB sneak</button></div>` : ""}`;
  } else if (ds.mode === "pass" || ds.mode === "pa") {
    const fam = ds.mode === "pass" ? "pass" : "pa";
    const hints: Record<string, string> = { short: "0-9 yds, high %", medium: "10-19, chains", deep: "20+, stops clock if inc." };
    body = `<div class="lbl">Depth</div><div class="grid3">${(["short", "medium", "deep"] as const).map((d) => `<button class="${ds.depth === d ? "on" : ""}" data-depth="${d}">${d[0].toUpperCase() + d.slice(1)}<span class="hint">${hints[d]}</span></button>`).join("")}</div>
      <div class="lbl">Side</div><div class="grid3">${DIRS.map(([d, l]) => `<button data-act='${play(`${fam}_${ds.depth}_${d}`)}'>${l}</button>`).join("")}</div>
      ${s.yl >= 30 && fam === "pass" ? `<div class="sit"><button data-act='${play("hail_mary")}'>Hail Mary</button></div>` : ""}`;
  } else {
    body = `<div class="grid3"><button data-act='${play("rpo")}'>RPO</button><button data-act='${play("screen")}'>Screen</button><button data-act='${play("gadget")}'>Trick play</button></div>`;
  }
  const tempo = `<div class="lbl">Tempo</div><div class="grid3">${[["hurry", "No huddle"], ["normal", "Huddle"], ["milk", "Milk it"]].map(([t, l]) => `<button class="${ds.tempo === t ? "on" : ""}" data-tempo="${t}">${l}</button>`).join("")}</div>`;
  const fgOk = s.yl + 17 <= 68;
  const sit = `<div class="sit">
    ${s.running && s.tos[0] > 0 ? `<button data-act='{"type":"timeout","team":0}'>Timeout (${s.tos[0]})</button>` : ""}
    <button data-act='{"type":"spike"}'>Spike</button><button data-act='{"type":"kneel"}'>Kneel</button>
    ${fgOk ? `<button data-act='{"type":"fg"}'>FG (${s.yl + 17} yd)</button>` : ""}<button data-act='{"type":"punt"}'>Punt</button></div>`;
  return `<div class="dock"><div class="tabs">${tabs.map(([m, l]) => `<button class="${ds.mode === m ? "on" : ""}" data-mode="${m}">${l}</button>`).join("")}</div>${body}${tempo}${sit}</div>`;
}
