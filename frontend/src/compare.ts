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
