import { describe, expect, it } from "vitest";
import { Engine, KICKOFF, PAT, SNAP, DONE, newState, defaultCtx } from "./engine";
import { loadNode } from "./load-node";
import { Rng } from "./rng";

const data = loadNode();
const eng = new Engine(data, defaultCtx());

describe("rng", () => {
  it("matches the Python mulberry32 sequence", () => {
    const r = new Rng(12345);
    expect(r.next()).toBe(0.9797282677609473);
    expect(r.next()).toBe(0.3067522644996643);
    expect(new Rng(0).next()).toBe(0.26642920868471265);
  });
});

describe("clock", () => {
  it("kneel bleeds the play clock and takes the two-minute warning", () => {
    const s = newState({ qtr: 4, clock: 125, running: true, warned: false });
    const e = eng.step(s, { type: "kneel" }, new Rng(1));
    expect(e.kind).toBe("warning");
    expect(s.clock).toBe(120);
    expect(s.running).toBe(false);
  });
  it("timeout stops the clock and is refused when none are left", () => {
    const s = newState({ qtr: 4, clock: 90, running: true, warned: true, tos: [1, 3] });
    expect(eng.step(s, { type: "timeout", team: 0 }, new Rng(1)).kind).toBe("timeout");
    expect(s.tos[0]).toBe(0);
    s.running = true;
    expect(eng.step(s, { type: "timeout", team: 0 }, new Rng(1)).kind).toBe("noop");
  });
  it("spike costs a down within three seconds", () => {
    const s = newState({ qtr: 4, clock: 30, running: true, warned: true, down: 2, togo: 5, yl: 30 });
    eng.step(s, { type: "spike" }, new Rng(1));
    expect(s.down).toBe(3);
    expect(s.clock).toBeGreaterThanOrEqual(25);
  });
});

describe("scoring and special teams", () => {
  it("touchdown -> PAT -> kickoff -> other team's ball", () => {
    let s = newState({ qtr: 4, clock: 60, warned: true, down: 1, togo: 1, yl: 1 });
    for (let seed = 0; seed < 100; seed++) {
      s = newState({ qtr: 4, clock: 60, warned: true, down: 1, togo: 1, yl: 1 });
      if (eng.step(s, { type: "play", call: "qb_sneak" }, new Rng(seed)).td) break;
    }
    expect(s.score[0]).toBe(6);
    expect(s.phase).toBe(PAT);
    eng.step(s, { type: "xp" }, new Rng(1));
    expect(s.phase).toBe(KICKOFF);
    eng.step(s, { type: "kickoff" }, new Rng(1));
    expect(s.phase).toBe(SNAP);
    expect(s.poss).toBe(1);
  });
  it("kickoff touchbacks land at the 35", () => {
    let tb = 0;
    for (let seed = 0; seed < 200; seed++) {
      const s = newState({ qtr: 4, clock: 60, phase: KICKOFF, kickTeam: 0, warned: true });
      const e = eng.step(s, { type: "kickoff" }, new Rng(seed));
      if (e.text === "Touchback") { expect(s.yl).toBe(65); tb++; }
    }
    expect(tb).toBeGreaterThan(20);
  });
});

describe("overtime", () => {
  it("tie after regulation starts a 10-minute OT with 2 timeouts", () => {
    const s = newState({ qtr: 4, clock: 3, running: true, warned: true, score: [20, 20], tos: [0, 1] });
    eng.step(s, { type: "kneel" }, new Rng(1));
    expect(s.qtr).toBe(5);
    expect(s.clock).toBe(600);
    expect(s.tos).toEqual([2, 2]);
    expect(s.phase).toBe(KICKOFF);
  });
  it("second-possession touchdown ends the game", () => {
    for (let seed = 0; seed < 100; seed++) {
      const s = newState({ qtr: 5, clock: 400, phase: SNAP, poss: 1, score: [23, 20], tos: [2, 2], otFirst: 0, otDone: [true, false], yl: 1, down: 1, togo: 1 });
      if (eng.step(s, { type: "play", call: "qb_sneak" }, new Rng(seed)).td) {
        expect(s.phase).toBe(DONE);
        expect(eng.value(s)).toBe(0);
        return;
      }
    }
    throw new Error("no TD found");
  });
});
