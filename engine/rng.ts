/** mulberry32, identical to sim/rng.py. */
export class Rng {
  state: number;
  constructor(seed: number) {
    this.state = seed >>> 0;
  }
  next(): number {
    this.state = (this.state + 0x6d2b79f5) >>> 0;
    let t = this.state;
    let r = Math.imul(t ^ (t >>> 15), 1 | t);
    r = (r + Math.imul(r ^ (r >>> 7), 61 | r)) ^ r;
    return ((r ^ (r >>> 14)) >>> 0) / 4294967296;
  }
  below(n: number): number {
    return Math.floor(this.next() * n);
  }
  chance(p: number): boolean {
    return this.next() < p;
  }
  pickWeighted(probs: number[]): number {
    let tot = 0;
    for (const p of probs) tot += p;
    const u = this.next() * tot;
    let acc = 0;
    for (let i = 0; i < probs.length; i++) {
      acc += probs[i];
      if (u < acc) return i;
    }
    return probs.length - 1;
  }
  fork(): Rng {
    return new Rng(Math.floor(this.next() * 4294967296));
  }
}
