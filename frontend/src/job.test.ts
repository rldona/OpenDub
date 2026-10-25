import { describe, expect, it } from "vitest";
import type { JobSummary } from "./api";
import { apply, newJob, overall, timing, type JobEvent } from "./job";

const summary: JobSummary = {
  id: "abcdefghijk", status: "running", error: null, created: "", finished: null,
  options: { url: "abcdefghijk", separate: true, tts: "clone", engine: "chatterbox", voice: "es-ES-AlvaroNeural",
    bg_volume: 0, keep_translation: false },
};
const run = (events: Partial<JobEvent>[]) =>
  events.reduce((j, e, i) => apply(j, { t: 100 + i, type: "log", ...e } as JobEvent), newJob(summary));

describe("job progress", () => {
  it("skips the phases a later one starts before, and counts them done", () => {
    const j = run([{ type: "status", status: "running" }, { type: "phase", name: "Download", state: "done" },
      { type: "phase", name: "Translation", state: "start" }]);
    expect(j.phases.Transcription?.state).toBe("skipped");
    expect(overall(j)).toBeCloseTo((1 + 1 + 2) / 100);
  });

  it("moves the voice phase with the first pass over every segment, never backwards", () => {
    const base: Partial<JobEvent>[] = [{ type: "phase", name: "TTS", state: "start" },
      { type: "log", message: "Cloned voice: engine chatterbox · 10 segments" }];
    const half = run([...base, { type: "progress", task: "Cloning voice", completed: 5, total: 10 }]);
    expect(half.phaseFrac.TTS).toBeCloseTo(0.3);
    const later = run([...base, { type: "progress", task: "Cloning voice", completed: 10, total: 10 },
      { type: "progress", task: "Cloning voice", completed: 1, total: 3 }]);
    expect(later.phaseFrac.TTS!).toBeGreaterThanOrEqual(0.6);
    expect(later.firstPassAt).not.toBeNull();
  });

  it("estimates the time left only once there is enough to go on, and says when it is finishing", () => {
    const j = run([{ type: "status", status: "running" }, { type: "phase", name: "Download", state: "done" },
      { type: "phase", name: "Transcription", state: "done" }, { type: "phase", name: "Separation", state: "done" },
      { type: "phase", name: "Translation", state: "done" }]);
    expect(timing(j, j.startedAt! + 10).left).toBeNull(); // under 20 s: no estimate yet
    expect(timing(j, j.startedAt! + 60).left).toBeGreaterThan(0);
    const cancelled = apply(j, { t: 200, type: "status", status: "cancelled" });
    expect(cancelled.finishedAt).toBe(200);
    expect(timing(cancelled, 999).left).toBeNull();
  });
});
