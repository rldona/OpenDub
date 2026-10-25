// The server's API (src/opendub/web/app.py), typed.

export type Engine = "chatterbox" | "indextts" | "cosyvoice";
export type EngineChoice = Engine | "auto";
export type Status = "pending" | "queued" | "running" | "done" | "error";

export interface JobOptions {
  url: string;
  separate: boolean;
  tts: "clone" | "edge";
  engine: EngineChoice;
  voice: string;
  bg_volume: number;
  keep_translation: boolean;
}

export interface JobSummary {
  id: string;
  status: Status;
  error: string | null;
  created: string;
  finished: string | null;
  options: JobOptions;
}

export interface Output {
  version: string;
  engine: string;
  date: string;
  current: boolean;
  issues: number;
  retouched: number; // sentences a retouch spoke again over the dub before it
}

export interface Video {
  id: string;
  title: string | null;
  duration: number | null;
  status: Status;
  error: string | null;
  date: string | null;
  engine: string | null;
  reference_f0_hz: number | null;
  clips: number;
  issues: number;
  options: JobOptions | null;
  outputs: Output[];
}

export interface Segment {
  id: number;
  start: number;
  end: number;
  original: string;
  text: string;
  slot: number;
  max_chars: number | null;
  edited: boolean;
}

export interface Translation {
  segments: Segment[];
  chars_per_second: number | null;
  needs_regeneration: boolean;
  pending: number[]; // edited since the latest dub: what a retouch speaks again
}

export type IssueKind = "fallback" | "floor" | "overflow" | "abnormal" | "glossary" | "repaired" | "delayed";

export type Register = "auto" | "tu" | "usted";
export type Variant = "auto" | "es-ES" | "latam";

export interface Term {
  source: string;
  target: string; // empty: kept as in the original
}

/** style.json: how a translation reads (src/opendub/style.py). */
export interface Style {
  register: Register;
  variant: Variant;
  terms: Term[];
  notes: string;
}

export interface VideoStyle {
  video: Style;
  global: Style;
  applied: Style;
  used: string[]; // glossary terms the video says
  stale: boolean; // the style changed since the translation was made
}

export interface Issue {
  id: number;
  kind: IssueKind;
  message: string;
  start: number | null;
  text: string | null;
  wav: string | null;
}

export interface Clip {
  id: number;
  start: number;
  slot: number;
  raw_duration: number;
  tempo: number;
  factor: number;
  voice: string;
  text: string;
}

export interface VersionDetail {
  version: string;
  engine: string | null;
  date: string | null;
  current: boolean;
  stats: {
    clips: number;
    voice_seconds: number | null;
    sped_up: number;
    shortened: number | null;
    below_floor: number;
    redone: number;
    edge: number;
    retouched: number[];
  };
  issues: Issue[];
  clips: Clip[];
}

export interface EngineStatus {
  id: EngineChoice;
  name: string;
  installed: boolean;
  setup: string | null;
}

export interface ServerStatus {
  version: string;
  work_root: string;
  running: number;
  queued: number;
}

export class ApiError extends Error {
  constructor(message: string, readonly status: number) {
    super(message);
  }
}

async function call<T>(path: string, init: RequestInit = {}): Promise<T> {
  let r: Response;
  try {
    r = await fetch(path, { headers: { "Content-Type": "application/json" }, ...init });
  } catch {
    throw new ApiError("unreachable", 0);
  }
  if (!r.ok) {
    let message = r.statusText;
    try {
      const body = await r.json();
      message = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
    } catch {
      /* not JSON */
    }
    throw new ApiError(message, r.status);
  }
  return r.json() as Promise<T>;
}

export const api = {
  status: () => call<ServerStatus>("/status"),
  engines: () => call<EngineStatus[]>("/engines"),
  jobs: () => call<JobSummary[]>("/jobs"),
  job: (id: string) => call<JobSummary>(`/jobs/${id}`),
  submit: (options: JobOptions) => call<JobSummary>("/jobs", { method: "POST", body: JSON.stringify(options) }),
  videos: () => call<Video[]>("/videos"),
  video: (id: string) => call<Video>(`/videos/${id}`),
  translation: (id: string) => call<Translation>(`/videos/${id}/translation`),
  saveTranslation: (id: string, edits: { id: number; text: string }[]) =>
    call<Translation>(`/videos/${id}/translation`, { method: "PUT", body: JSON.stringify(edits) }),
  style: () => call<Style>("/style"),
  saveStyle: (style: Style) => call<Style>("/style", { method: "PUT", body: JSON.stringify(style) }),
  videoStyle: (id: string) => call<VideoStyle>(`/videos/${id}/style`),
  saveVideoStyle: (id: string, style: Style) =>
    call<VideoStyle>(`/videos/${id}/style`, { method: "PUT", body: JSON.stringify(style) }),
  retouch: (id: string, takes: number[]) =>
    call<JobSummary & { segments: number[] }>(`/videos/${id}/retouch`, { method: "POST", body: JSON.stringify({ takes }) }),
  version: (id: string, version: string) =>
    call<VersionDetail>(`/videos/${id}/versions/${encodeURIComponent(version)}`),
  deleteVersion: (id: string, version: string) =>
    call<{ outputs: Output[] }>(`/videos/${id}/outputs/${encodeURIComponent(version)}`, { method: "DELETE" }),
};

export const media = {
  thumbnail: (id: string) => `/videos/${id}/thumbnail`,
  video: (id: string, version: string | null) =>
    version ? `/videos/${id}/outputs/${encodeURIComponent(version)}.mp4` : `/videos/${id}/output.mp4`,
  events: (id: string) => `/jobs/${id}/events`,
};

/** Dub a video again with its last options, changed by `overrides`. */
export async function redub(id: string, fallback: JobOptions, overrides: Partial<JobOptions> = {}) {
  const saved = await api.job(id).catch(() => null);
  const base = saved?.options ?? fallback;
  return api.submit({ ...base, ...overrides, url: id });
}
