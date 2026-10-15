export function hashStr(s: string): number {
  let h = 2166136261 >>> 0;
  for (let i = 0; i < s.length; i++) { h ^= s.charCodeAt(i); h = Math.imul(h, 16777619) >>> 0; }
  return h >>> 0;
}
export const clockStr = (secs: number) => `${Math.floor(secs / 60)}:${String(secs % 60).padStart(2, "0")}`;
export const ordinal = (n: number) => { const s = ["th", "st", "nd", "rd"], v = n % 100; return n + (s[(v - 20) % 10] || s[v] || s[0]); };
export const pct = (x: number, d = 1) => `${(100 * x).toFixed(d)}%`;
export const todayKey = (d = new Date()) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
export function daysBetween(aKey: string, bKey: string): number {
  const [ay, am, ad] = aKey.split("-").map(Number), [by, bm, bd] = bKey.split("-").map(Number);
  return Math.round((Date.UTC(by, bm - 1, bd) - Date.UTC(ay, am - 1, ad)) / 86400000);
}
export const el = (html: string): HTMLElement => { const t = document.createElement("template"); t.innerHTML = html.trim(); return t.content.firstElementChild as HTMLElement; };
export const esc = (s: string) => s.replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]!));
export function ratingColor(r: number): string {
  // red (<=60) -> yellow (77) -> green (>=90)
  const t = r <= 77 ? Math.max(0, (r - 60) / 17) * 0.5 : 0.5 + Math.min(1, (r - 77) / 13) * 0.5;
  const hue = 0 + t * 120;
  return `hsl(${hue.toFixed(0)} 85% 55%)`;
}
export const downStr = (d: number, togo: number, yl: number) => `${ordinal(d)} & ${togo >= yl ? "Goal" : togo}`;
export const spotTitle = (yl: number, off: string, def: string) => (yl > 50 ? `${off} ${100 - yl}` : yl === 50 ? "50" : `${def} ${yl}`);
