import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import { api, media, type JobSummary, type Status } from "./api";

export const PHASES = ["Download", "Transcription", "Separation", "Translation", "TTS", "Mix"] as const;
export type Phase = (typeof PHASES)[number];
// Share of a dub's time per phase, measured on a 28-minute video with a cloned voice
const WEIGHTS: Record<Phase, number> = { Download: 1, Transcription: 1, Separation: 2, Translation: 9, TTS: 86, Mix: 1 };

type PhaseState = "pending" | "active" | "done" | "error" | "skipped";

export interface LogLine {
  level: string;
  message: string;
}

export interface LiveJob {
  id: string;
  title: string | null;
  status: Status;
  error: string | null;
  engine: string;
  phases: Partial<Record<Phase, { state: PhaseState; seconds?: number }>>;
  active: Phase | null;
  task: { task: string; completed: number; total: number | null } | null;
  logs: LogLine[];
  startedAt: number | null;
  finishedAt: number | null;
  // TTS progress: the first pass speaks every segment, maybe over several progress bars
  segments: number | null;
  clipsDone: number;
  lastCompleted: number;
  firstPassAt: number | null;
  laterBatches: number;
  phaseFrac: Partial<Record<Phase, number>>;
}

export interface JobEvent {
  type: "status" | "phase" | "progress" | "log";
  t: number;
  status?: Status;
  error?: string;
  name?: Phase;
  state?: "start" | "done" | "error";
  seconds?: number;
  task?: string;
  completed?: number;
  total?: number | null;
  level?: string;
  message?: string;
}

export function newJob(summary: JobSummary): LiveJob {
  return {
    id: summary.id, title: null, status: summary.status, error: summary.error, engine: summary.options.engine,
    phases: {}, active: null, task: null, logs: [], startedAt: null, finishedAt: null, segments: null,
    clipsDone: 0, lastCompleted: 0, firstPassAt: null, laterBatches: 0, phaseFrac: {},
  };
}

/** A job after one more of its server events (pure: tested in job.test.ts). */
export function apply(job: LiveJob, e: JobEvent): LiveJob {
  const j: LiveJob = { ...job, phases: { ...job.phases }, phaseFrac: { ...job.phaseFrac } };
  if (e.type === "status" && e.status) {
    j.status = e.status;
    if (e.error) j.error = e.error;
    if (e.status === "running") j.startedAt = e.t;
    if (e.status === "done" || e.status === "error" || e.status === "cancelled") j.finishedAt = e.t;
  } else if (e.type === "phase" && e.name) {
    j.phases[e.name] = { state: e.state === "start" ? "active" : (e.state ?? "done"), seconds: e.seconds };
    if (e.state === "start") {
      j.active = e.name;
      j.task = null;
      // a phase that starts after an earlier one never did means that one was skipped (Separation)
      PHASES.slice(0, PHASES.indexOf(e.name)).forEach((p) => {
        if (!j.phases[p]) j.phases[p] = { state: "skipped" };
      });
    }
  } else if (e.type === "progress") {
    const completed = e.completed ?? 0;
    j.task = { task: e.task ?? "", completed, total: e.total ?? null };
    // the overall bar never goes back: later, smaller bars (quality check, shortening) don't reset it
    if (j.active === "TTS" && j.segments) {
      // The first pass speaks every segment and is ~60% of the phase. What follows (fitting, quality
      // check, shortening) has no known total: each later batch moves the bar a bit, never to the end.
      if (completed < j.lastCompleted) {
        if (j.firstPassAt) j.laterBatches += 1;
        j.clipsDone += j.lastCompleted;
      }
      j.lastCompleted = completed;
      const first = Math.min(1, (j.clipsDone + completed) / j.segments);
      if (first >= 1 && !j.firstPassAt) j.firstPassAt = e.t;
      const later = j.firstPassAt ? 1 - 0.6 ** j.laterBatches : 0;
      j.phaseFrac.TTS = Math.max(j.phaseFrac.TTS ?? 0, 0.6 * first + 0.4 * later * 0.9);
    } else if (j.active && e.total) {
      j.phaseFrac[j.active] = Math.max(j.phaseFrac[j.active] ?? 0, Math.min(1, completed / e.total));
    }
  } else if (e.type === "log" && e.message) {
    j.logs = [...job.logs, { level: e.level ?? "info", message: e.message }].slice(-6);
    const title = /^\s*(.+?) · \d+s · language/.exec(e.message);
    if (title) j.title = title[1];
    const segments = /· (\d+) segments$/.exec(e.message); // "Cloned voice: … · 353 segments"
    if (segments && j.active === "TTS") j.segments = Number(segments[1]);
  }
  return j;
}

export function overall(job: LiveJob): number {
  if (job.status === "done") return 1;
  let done = 0;
  let total = 0;
  for (const p of PHASES) {
    total += WEIGHTS[p];
    const state = job.phases[p]?.state;
    if (state === "done" || state === "skipped") done += WEIGHTS[p];
    else if (state === "active") done += WEIGHTS[p] * (job.phaseFrac[p] ?? 0);
  }
  return done / total;
}

/** "took …", "… elapsed · about N min left", or what's honest when there's no estimate. */
export function timing(job: LiveJob, now: number): { elapsed: number | null; left: number | null; finishing: boolean } {
  if (!job.startedAt) return { elapsed: null, left: null, finishing: false };
  const end = job.status === "running" ? now : (job.finishedAt ?? now);
  const elapsed = Math.max(0, end - job.startedAt);
  if (job.status !== "running") return { elapsed, left: null, finishing: false };
  if (job.active === "TTS" && job.firstPassAt) return { elapsed, left: null, finishing: true };
  const f = overall(job);
  const left = f >= 0.05 && elapsed >= 20 ? (elapsed * (1 - f)) / f : null;
  return { elapsed, left, finishing: false };
}

interface JobContext {
  job: LiveJob | null;
  queued: JobSummary[];
  /** Bumped whenever a job ends, so pages reload what it changed. */
  finished: number;
  refresh: () => void;
}

const Context = createContext<JobContext | null>(null);

export function JobProvider({ children }: { children: ReactNode }) {
  const [job, setJob] = useState<LiveJob | null>(null);
  const [queued, setQueued] = useState<JobSummary[]>([]);
  const [finished, setFinished] = useState(0);
  const watching = useRef<string | null>(null);
  const source = useRef<EventSource | null>(null);

  const refresh = useCallback(async () => {
    const active = await api.jobs().catch(() => null);
    if (!active) return;
    setQueued(active.filter((j) => j.status === "queued"));
    const first = active[0];
    if (!first || watching.current === first.id) return;
    // a new job to follow: replay its events from the start over SSE
    source.current?.close();
    watching.current = first.id;
    setJob(newJob(first));
    // a cached download logs no title: take it from the video
    api.video(first.id)
      .then((v) => setJob((j) => (j && j.id === first.id && !j.title ? { ...j, title: v.title } : j)))
      .catch(() => undefined);
    const es = new EventSource(media.events(first.id));
    source.current = es;
    es.onmessage = (msg) => setJob((j) => (j && j.id === first.id ? apply(j, JSON.parse(msg.data)) : j));
    es.addEventListener("end", () => {
      es.close();
      source.current = null;
      watching.current = null;
      setFinished((n) => n + 1);
      void refresh();
    });
  }, []);

  useEffect(() => {
    void refresh();
    const timer = window.setInterval(() => {
      if (!document.hidden) void refresh();
    }, 5000);
    return () => {
      window.clearInterval(timer);
      source.current?.close();
    };
  }, [refresh]);

  return (
    <Context.Provider value={{ job, queued, finished, refresh: () => void refresh() }}>{children}</Context.Provider>
  );
}

export function useJobs(): JobContext {
  const ctx = useContext(Context);
  if (!ctx) throw new Error("useJobs outside JobProvider");
  return ctx;
}

/** A clock that ticks every `ms` while `on`, for elapsed/left texts. */
export function useNow(on: boolean, ms = 5000): number {
  const [now, setNow] = useState(() => Date.now() / 1000);
  useEffect(() => {
    if (!on) return;
    const timer = window.setInterval(() => setNow(Date.now() / 1000), ms);
    return () => window.clearInterval(timer);
  }, [on, ms]);
  return now;
}
