// The server's API (src/opendub/web/app.py), typed.

export type Engine = "chatterbox" | "indextts" | "cosyvoice";
export type EngineChoice = Engine | "auto";
export type Status = "pending" | "queued" | "running" | "done" | "review" | "error" | "cancelled";

export interface JobOptions {
  url: string;
  separate: boolean;
  tts: "clone" | "edge";
  engine: EngineChoice;
  voice: string;
  bg_volume: number;
  keep_translation: boolean;
  multi_speaker?: boolean; // several voices: diarize and give each speaker their own voice
  review?: boolean; // stop after the translation, to edit it before the voice ("review" status)
  then?: Engine[]; // engines to dub with next, one after another (each its own version)
}

export interface JobSummary {
  id: string;
  status: Status;
  error: string | null;
  error_code?: string | null; // a common phase failure (errors.PhaseError): said in the page's language
  error_params?: Record<string, string> | null;
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
  error_code?: string | null;
  error_params?: Record<string, string> | null;
  date: string | null;
  engine: string | null;
  reference_f0_hz: number | null;
  several_voices: boolean; // the latest dub gave each speaker their own voice
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
  speaker: string | null; // several voices: A, B, C…
}

export interface Translation {
  segments: Segment[];
  chars_per_second: number | null;
  needs_regeneration: boolean;
  pending: number[]; // edited since the latest dub: what a retouch speaks again
  clips_available: boolean; // false when the voice clips were deleted to save space
}

export interface Storage {
  groups: { id: "source" | "stems" | "raw" | "clips" | "exports"; bytes: number; files: number }[];
  kept: number; // bytes that always stay: versions, translation, tts.json…
}

export type IssueKind = "fallback" | "floor" | "overflow" | "abnormal" | "glossary" | "repaired" | "delayed";

export type ExportFormat = "mkv" | "m4a" | "srt" | "srt-orig";

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

export interface SpeakerVoice {
  engine: string; // a cloning engine, or "edge" for a stock voice
  voice: string | null; // the stock voice
  reference: string | null;
  gender: string | null;
  stock: string | null; // a cloned speaker's last resort
}

export interface Speaker {
  id: string;
  name: string | null;
  seconds: number | null;
  f0_hz: number | null;
  gender: "female" | "male" | null;
  sentences: number;
  voice: SpeakerVoice | null; // how the latest dub spoke them
  sample: string | null;
}

export interface ServerStatus {
  version: string;
  work_root: string;
  running: number;
  queued: number;
  diarizer: { installed: boolean; setup: string | null };
}

export class ApiError extends Error {
  // message: the server's technical text (English); code and params: what the page translates (errors.ts)
  constructor(message: string, readonly status: number, readonly code?: string, readonly params: Record<string, string | number> = {}) {
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
    let code: string | undefined;
    let params: Record<string, string | number> = {};
    try {
      const { detail } = await r.json();
      if (typeof detail === "string") message = detail;
      else if (detail && typeof detail.code === "string") ({ code, message, params = {} } = detail);
      else message = JSON.stringify(detail); // FastAPI's own validation errors
    } catch {
      /* not JSON */
    }
    throw new ApiError(message, r.status, code, params);
  }
  return r.json() as Promise<T>;
}

export const api = {
  status: () => call<ServerStatus>("/status"),
  engines: () => call<EngineStatus[]>("/engines"),
  jobs: () => call<JobSummary[]>("/jobs"),
  job: (id: string) => call<JobSummary>(`/jobs/${id}`),
  cancel: (id: string) => call<JobSummary>(`/jobs/${id}/cancel`, { method: "POST" }),
  submit: (options: JobOptions) => call<JobSummary>("/jobs", { method: "POST", body: JSON.stringify(options) }),
  videos: () => call<Video[]>("/videos"),
  video: (id: string) => call<Video>(`/videos/${id}`),
  translation: (id: string) => call<Translation>(`/videos/${id}/translation`),
  saveTranslation: (id: string, edits: { id: number; text: string }[]) =>
    call<Translation>(`/videos/${id}/translation`, { method: "PUT", body: JSON.stringify(edits) }),
  /** Corrected subtitles (.ass, .vtt, .srt) back into the translation: texts as hand edits, names as speakers. */
  importSubtitles: (id: string, name: string, text: string) =>
    call<{ imported: { texts: number[]; speakers: number[] }; translation: Translation; speakers: Speaker[] }>(
      `/videos/${id}/translation/import`, { method: "POST", body: JSON.stringify({ name, text }) }),
  speakers: (id: string) => call<Speaker[]>(`/videos/${id}/speakers`),
  renameSpeaker: (id: string, speaker: string, name: string) =>
    call<Speaker[]>(`/videos/${id}/speakers/${speaker}`, { method: "PUT", body: JSON.stringify({ name }) }),
  mergeSpeaker: (id: string, speaker: string, into: string) =>
    call<{ moved: number; speakers: Speaker[]; translation: Translation }>(
      `/videos/${id}/speakers/${speaker}/merge`, { method: "POST", body: JSON.stringify({ into }) }),
  changeSpeakers: (id: string, changes: { id: number; speaker: string }[]) =>
    call<{ speakers: Speaker[]; translation: Translation }>(
      `/videos/${id}/segments/speakers`, { method: "PUT", body: JSON.stringify(changes) }),
  storage: (id: string) => call<Storage>(`/videos/${id}/storage`),
  deleteStorage: (id: string, group: string) =>
    call<Storage & { freed: number }>(`/videos/${id}/storage/${group}`, { method: "DELETE" }),
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
  /** A version as srt (the dubbed voice), srt-orig, mkv (both audio tracks and subtitles) or m4a. */
  exported: (id: string, version: string | null, format: ExportFormat) =>
    `/videos/${id}/outputs/${encodeURIComponent(version ?? "latest")}/export/${format}`,
  /** The translation as subtitles: ass and vtt with who says each sentence, srt without. */
  subtitles: (id: string, format: "ass" | "vtt" | "srt") => `/videos/${id}/translation/export/${format}`,
};

/** Dub a video again with its last options, changed by `overrides`. */
export async function redub(id: string, fallback: JobOptions, overrides: Partial<JobOptions> = {}) {
  const saved = await api.job(id).catch(() => null);
  const base = saved?.options ?? fallback;
  // a review is asked for each time: a job saved with it doesn't make every later dub stop
  return api.submit({ ...base, review: false, ...overrides, url: id });
}
