import { describe, expect, it } from "vitest";
import type { VersionDetail } from "./api";
import { differences } from "./compare";

const version = (clips: [number, string, number][], issues: number[] = []): VersionDetail => ({
  version: "v", engine: "chatterbox", date: null, current: false,
  stats: { clips: clips.length, voice_seconds: null, sped_up: 0, shortened: 0, below_floor: 0, redone: 0, edge: 0, retouched: [] },
  issues: issues.map((id) => ({ id, kind: "overflow", message: "lasts 2s at 1.25x, slot 1s (+0.50s)", start: id, text: null, wav: null })),
  clips: clips.map(([id, text, tempo]) => ({ id, start: id, slot: 3, raw_duration: 2, tempo, factor: 1, voice: "chatterbox", text })),
});

describe("compare", () => {
  it("lists only the sentences said differently or with an issue on either side", () => {
    const a = version([[1, "Hola.", 1], [2, "¿Qué tal?", 1.2], [3, "Adiós.", 1]], [2]);
    const b = version([[1, "Hola.", 1], [2, "¿Qué tal?", 1], [3, "Hasta luego.", 1]]);
    const d = differences(a, b);
    expect(d.map((x) => x.id)).toEqual([2, 3]);
    expect(d[0].a.issues).toHaveLength(1);
    expect(d[0].a.tempo).toBe(1.2);
    expect(d[1].a.text).toBe("Adiós.");
    expect(d[1].b.text).toBe("Hasta luego.");
    expect(differences(null, b)).toEqual([]);
  });
});
