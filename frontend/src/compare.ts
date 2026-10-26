import type { Clip, Issue, VersionDetail } from "./api";

export interface SideDiff {
  issues: Issue[];
  tempo: number | null; // atempo, when the clip was sped up
  text: string | null; // shown when the two sides said different things
}

/** Segments the two versions fitted differently: issues on either side, or different spoken text. */
export function differences(a: VersionDetail | null, b: VersionDetail | null) {
  if (!a || !b) return [];
  const byId = (d: VersionDetail) => new Map(d.clips.map((c) => [c.id, c]));
  const issues = (d: VersionDetail) => {
    const m = new Map<number, Issue[]>();
    d.issues.forEach((i) => m.set(i.id, [...(m.get(i.id) ?? []), i]));
    return m;
  };
  const [ca, cb, ia, ib] = [byId(a), byId(b), issues(a), issues(b)];
  const tempo = (c: Clip | undefined) => (c && c.tempo > 1.0 ? c.tempo : null);
  const out: { id: number; start: number; a: SideDiff; b: SideDiff }[] = [];
  for (const [id, x] of ca) {
    const y = cb.get(id);
    const differentText = !!y && x.text !== y.text;
    if (!ia.has(id) && !ib.has(id) && !differentText) continue;
    out.push({
      id, start: x.start,
      a: { issues: ia.get(id) ?? [], tempo: tempo(x), text: differentText ? x.text : null },
      b: { issues: ib.get(id) ?? [], tempo: tempo(y), text: differentText ? y!.text : null },
    });
  }
  return out.sort((p, q) => p.id - q.id);
}

/** How B follows A, `drift` seconds behind it (negative: ahead): a jump only past a second, else a
 *  slightly faster or slower B until it catches up. A jump makes the browser fetch and decode from
 *  there, which costs time and so more drift: jumping at every small drift is what made B stutter. */
export function followB(drift: number): { jump: boolean; rate: number } {
  if (Math.abs(drift) > JUMP_S) return { jump: true, rate: 1 };
  if (Math.abs(drift) < CLOSE_S) return { jump: false, rate: 1 };
  return { jump: false, rate: 1 + Math.max(-MAX_NUDGE, Math.min(MAX_NUDGE, drift * 0.5)) };
}

const JUMP_S = 1.0;
const CLOSE_S = 0.04;
const MAX_NUDGE = 0.08;
