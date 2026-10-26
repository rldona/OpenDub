import { useEffect, useMemo, useState, type FormEvent } from "react";
import { api, redub, type EngineChoice, type JobOptions, type Video } from "../api";
import { useEngines } from "../App";
import { ENGINES, engineShort } from "../catalog";
import { EngineTag, StatusBadge, Thumb } from "../components";
import { clock, duration, when } from "../format";
import { overall, PHASES, timing, useJobs, useNow, type LiveJob } from "../job";
import { usePrefs } from "../prefs";
import { errorText, jobErrorText } from "../errors";

export function Library() {
  const { t } = usePrefs();
  const { finished } = useJobs();
  const [videos, setVideos] = useState<Video[] | null>(null);
  const load = () => api.videos().then(setVideos).catch(() => undefined);
  useEffect(() => {
    void load();
    const timer = window.setInterval(() => !document.hidden && void load(), 10000);
    return () => window.clearInterval(timer);
  }, [finished]);
  return (
    <>
      <div>
        <div className="crumbs">{t("workspace")} / {t("library")}</div>
        <h1>{t("library")}</h1>
      </div>
      <NewDub onSubmitted={load} />
      <NowDubbing />
      <VideoTable videos={videos} onChanged={load} />
    </>
  );
}

/** The options a new dub starts with (Preferences), as the API takes them. */
export function useDefaultOptions(): JobOptions {
  const { prefs } = usePrefs();
  return {
    url: "", tts: prefs.tts, engine: prefs.engine, separate: prefs.separate, bg_volume: prefs.bgVolume,
    voice: prefs.voice, keep_translation: false,
  };
}

function NewDub({ onSubmitted }: { onSubmitted: () => void }) {
  const { prefs, t } = usePrefs();
  const defaults = useDefaultOptions();
  const engines = useEngines();
  const { refresh } = useJobs();
  const [url, setUrl] = useState("");
  const [tts, setTts] = useState(defaults.tts);
  const [engine, setEngine] = useState<EngineChoice>(defaults.engine);
  const [separate, setSeparate] = useState(defaults.separate);
  const [volume, setVolume] = useState(defaults.bg_volume);
  const [multi, setMulti] = useState<boolean | null>(null); // null: the default, on when Nemotron is installed
  const [diarizer, setDiarizer] = useState<{ installed: boolean; setup: string | null } | null>(null);
  useEffect(() => {
    api.status().then((s) => setDiarizer(s.diarizer)).catch(() => undefined);
  }, []);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  // several voices by default (docs/v2-plan.md, blind listening): a single-voice video keeps one voice anyway
  const several = (multi ?? true) && !!diarizer?.installed;

  const installed = (id: EngineChoice) => engines?.find((e) => e.id === id)?.installed ?? true;
  const missing = (engines ?? []).filter((e) => !e.installed && e.id !== "auto");
  const note = tts === "edge" ? t("note_stock", { v: prefs.voice })
    : engine === "auto" ? t("note_auto") : t(ENGINES.find((e) => e.id === engine)!.note);

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!url.trim()) {
      setError(t("url_required"));
      return;
    }
    setBusy(true);
    try {
      await api.submit({ ...defaults, url: url.trim(), tts, engine, separate, bg_volume: volume, multi_speaker: several });
      setUrl("");
      setError(null);
      refresh();
      onSubmitted();
    } catch (err) {
      setError(errorText(err, t));
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="card stack" onSubmit={submit} aria-labelledby="new-dub" noValidate>
      <h2 id="new-dub">{t("new_dub")}</h2>
      <div className="row">
        <label htmlFor="url" className="sr-only">{t("youtube_link")}</label>
        <input id="url" className="input big" style={{ flex: "999 1 380px", minWidth: 0 }} type="url" value={url}
          placeholder={t("paste_link")} onChange={(e) => { setUrl(e.target.value); setError(null); }} />
        <button type="submit" className="btn primary big" style={{ flex: "1 0 130px" }} disabled={busy}>{t("dub")}</button>
      </div>
      {error && <p className="error" role="alert">{error}</p>}
      <div className="row" style={{ gap: "10px 20px" }}>
        <div className="segmented" role="radiogroup" aria-label={t("voice")}>
          <button type="button" role="radio" aria-checked={tts === "clone"} onClick={() => setTts("clone")}>{t("voice_clone")}</button>
          <button type="button" role="radio" aria-checked={tts === "edge"} onClick={() => setTts("edge")}>{t("voice_stock")}</button>
        </div>
        {tts === "clone" && (
          <div className="row" role="radiogroup" aria-label={t("engine")} style={{ gap: 6 }}>
            {(["auto", ...ENGINES.map((e) => e.id)] as EngineChoice[]).map((id) => (
              <button key={id} type="button" role="radio" className="chip" aria-checked={engine === id}
                disabled={!installed(id)} onClick={() => setEngine(id)}
                title={installed(id) ? undefined : engines?.find((e) => e.id === id)?.setup ?? undefined}>
                {id !== "auto" && <span className={`dot ${id}`} />}
                {id === "auto" ? t("auto") : engineShort(id)}
                {!installed(id) && <span className="faint small">· {t("not_installed")}</span>}
              </button>
            ))}
          </div>
        )}
        <span className="small muted">{note} · <a href="#/engines">{t("about_engines")}</a></span>
      </div>
      {tts === "clone" && missing.length > 0 && (
        <p className="small faint" style={{ margin: 0 }}>
          {missing.map((e) => t("install_hint", { e: e.name, cmd: e.setup ?? "" })).join(" · ")}
        </p>
      )}
      <details className="small muted">
        <summary style={{ cursor: "pointer" }}>
          {t("more_options")} · {separate ? t("options_music", { db: volume }) : t("options_original", { db: volume })}
          {several ? ` · ${t("several_voices").toLowerCase()}` : ""}
        </summary>
        <div className="row" style={{ marginTop: 12, gap: "12px 28px" }}>
          <label className="row" style={{ gap: 8, cursor: diarizer?.installed ? "pointer" : "default", color: "var(--text)" }}
            title={diarizer && !diarizer.installed ? t("install_hint", { e: "Nemotron 3 Diarization", cmd: diarizer.setup ?? "" }) : undefined}>
            <input type="checkbox" checked={several} disabled={!diarizer?.installed} style={{ accentColor: "var(--accent)" }}
              onChange={(e) => setMulti(e.target.checked)} />
            {t("several_voices")}
            <span className="faint">· {diarizer && !diarizer.installed ? t("not_installed") : t("several_voices_hint")}</span>
          </label>
          <label className="row" style={{ gap: 8, cursor: "pointer", color: "var(--text)" }}>
            <input type="checkbox" checked={separate} style={{ accentColor: "var(--accent)" }}
              onChange={(e) => { setSeparate(e.target.checked); setVolume(e.target.checked ? 0 : -15); }} />
            {t("keep_music")}
          </label>
          <label className="field" style={{ minWidth: 240 }}>
            {t("bg_volume")} · {volume} dB
            <input type="range" min={-30} max={6} step={1} value={volume} style={{ accentColor: "var(--accent)" }}
              onChange={(e) => setVolume(Number(e.target.value))} />
          </label>
        </div>
      </details>
    </form>
  );
}

export function NowDubbing() {
  const { t, prefs } = usePrefs();
  const { job, queued } = useJobs();
  const [showLog, setShowLog] = useState(false);
  const live = !!job && (job.status === "running" || job.status === "queued");
  const now = useNow(live);
  if (!job) return null;
  const f = overall(job);
  const time = timing(job, now);
  const parts: string[] = [];
  if (job.status === "running" && job.task) {
    parts.push(`${t(job.active ?? "TTS")}${job.task.total ? ` · ${Math.round(job.task.completed)}/${Math.round(job.task.total)}` : ""}`);
  }
  if (time.elapsed != null) {
    if (job.status === "running") {
      parts.push(t("elapsed", { t: clock(time.elapsed) }));
      parts.push(time.finishing ? t("finishing") : time.left == null ? t("estimating")
        : time.left < 60 ? t("eta_sec") : t("eta_min", { m: Math.round(time.left / 60) }));
    } else {
      parts.push(t("took", { t: clock(time.elapsed) }));
    }
  }
  const failure = jobErrorText(job.error, job.errorCode, job.errorParams, t);
  const heading = job.status === "queued" ? t("queued_now") : job.status === "running" ? t("dubbing_now")
    : job.status === "error" ? t("job_failed", { msg: failure.text })
    : job.status === "cancelled" ? t("job_cancelled") : job.status === "review" ? t("job_review") : t("job_done");
  async function cancel() {
    if (!confirm(t("cancel_confirm", { v: job!.title ?? job!.id }))) return;
    await api.cancel(job!.id).catch(() => undefined);
  }
  return (
    <section className="card stack" aria-labelledby="now" style={{ padding: "16px 20px", gap: 12 }}>
      <div className="row" style={{ gap: "10px 16px" }}>
        <Thumb id={job.id} retry={`${job.status}:${job.active ?? ""}`} style={{ width: 88, flex: "none" }} />
        <div style={{ flex: "999 1 280px", minWidth: 0 }}>
          <h2 id="now" className={`kicker ${job.status === "error" ? "danger-text" : ""}`}
            title={job.status === "error" && failure.detail ? t("detail", { d: failure.detail }) : undefined}>{heading}</h2>
          <a href={`#/video/${job.id}`} style={{ display: "block", color: "var(--text)", fontWeight: 650, textDecoration: "none", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
            {job.title ?? job.id}
          </a>
          <div className="small muted">
            {parts.join(" · ")}
            {queued.length > 0 && ` · ${t("in_queue", { n: queued.length })}`}
          </div>
        </div>
        {job.engine && <EngineTag engine={job.engine === "auto" ? null : job.engine} extra={job.engine === "auto" ? t("auto") : undefined} />}
        {job.status !== "review" && <span className="num" style={{ fontSize: 20, fontWeight: 700 }}>{Math.floor(f * 100)}%</span>}
        {live && <button type="button" className="btn danger" onClick={() => void cancel()}>{t("cancel_job")}</button>}
        {job.status === "review" && <a className="btn primary" href={`#/video/${job.id}`}>{t("review_link")}</a>}
      </div>
      {job.status !== "review" && (
        <div className="progress" role="progressbar" aria-valuenow={Math.floor(f * 100)} aria-valuemin={0} aria-valuemax={100}>
          <div style={{ width: `${(f * 100).toFixed(1)}%` }} />
        </div>
      )}
      <Steps job={job} />
      {job.logs.length > 0 && (
        <div>
          <button type="button" className="btn" style={{ height: 32 }} aria-expanded={showLog} onClick={() => setShowLog(!showLog)}>
            {t("show_log")}
          </button>
          {showLog && (
            <ul className="log" lang={prefs.lang === "es" ? "en" : undefined}>
              {job.logs.slice().reverse().map((l, i) => <li key={i} className={l.level}>{l.message}</li>)}
            </ul>
          )}
        </div>
      )}
    </section>
  );
}

function Steps({ job }: { job: LiveJob }) {
  const { t } = usePrefs();
  return (
    <ol className="steps">
      {PHASES.map((p) => {
        const state = job.phases[p]?.state ?? "pending";
        const mark = state === "done" ? "✓" : state === "active" ? "●" : state === "error" ? "✕" : "○";
        return (
          <li key={p} className={state} aria-current={state === "active" ? "step" : undefined}>
            {mark} {t(p)}
          </li>
        );
      })}
    </ol>
  );
}

function VideoTable({ videos, onChanged }: { videos: Video[] | null; onChanged: () => void }) {
  const { t, prefs } = usePrefs();
  const defaults = useDefaultOptions();
  const { refresh } = useJobs();
  const [query, setQuery] = useState("");
  const shown = useMemo(() => {
    const q = query.trim().toLowerCase();
    return (videos ?? []).filter((v) => !q || (v.title ?? v.id).toLowerCase().includes(q));
  }, [videos, query]);

  async function start(id: string) {
    await redub(id, defaults).catch(() => undefined);
    refresh();
    onChanged();
  }

  return (
    <section className="stack" aria-labelledby="videos" style={{ gap: 12 }}>
      <div className="spread">
        <h2 id="videos">{t("videos")} <span className="faint" style={{ fontWeight: 400 }}>· {videos?.length ?? 0}</span></h2>
        <label>
          <span className="sr-only">{t("search_videos")}</span>
          <input type="search" className="input" style={{ width: 240, height: 36 }} placeholder={t("search")}
            value={query} onChange={(e) => setQuery(e.target.value)} />
        </label>
      </div>
      {videos && videos.length === 0 && <p className="muted">{t("no_videos")}</p>}
      {videos && videos.length > 0 && shown.length === 0 && <p className="muted">{t("no_match")}</p>}
      {shown.length > 0 && (
        <div className="table-box">
          <table className="data" style={{ minWidth: 860 }}>
            <thead>
              <tr>
                <th scope="col">{t("col_video")}</th>
                <th scope="col">{t("col_versions")}</th>
                <th scope="col">{t("col_latest")}</th>
                <th scope="col">{t("col_issues")}</th>
                <th scope="col">{t("col_status")}</th>
              </tr>
            </thead>
            <tbody>
              {shown.map((v) => {
                const counts = new Map<string, number>();
                v.outputs.forEach((o) => counts.set(o.engine, (counts.get(o.engine) ?? 0) + 1));
                const latest = v.outputs.find((o) => o.current);
                return (
                  <tr key={v.id}>
                    <td>
                      <a href={`#/video/${v.id}`} className="row" style={{ gap: 12, flexWrap: "nowrap", color: "var(--text)", textDecoration: "none" }}>
                        <Thumb id={v.id} style={{ width: 88, flex: "none" }} lazy />
                        <span>
                          <span style={{ display: "block", fontWeight: 650 }}>{v.title ?? v.id}</span>
                          <span className="small faint">{duration(v.duration)}</span>
                        </span>
                      </a>
                    </td>
                    <td>
                      <span className="row" style={{ gap: 4 }}>
                        {[...counts].map(([engine, n]) => <EngineTag key={engine} engine={engine} extra={n > 1 ? ` ×${n}` : undefined} />)}
                        {counts.size === 0 && <span className="faint">—</span>}
                      </span>
                    </td>
                    <td className="muted">{latest ? `${engineShort(latest.engine)} · ${when(latest.date, prefs.lang)}` : "—"}</td>
                    <td className={v.issues ? "warn-text" : "ok-text"}>{v.status === "done" ? v.issues : "—"}</td>
                    <td>
                      <span className="row" style={{ gap: 8 }}>
                        <StatusBadge status={v.status} />
                        {v.status === "review" && (
                          <a className="btn" style={{ height: 30 }} href={`#/video/${v.id}`}>{t("review_link")}</a>
                        )}
                        {(v.status === "error" || v.status === "pending" || v.status === "cancelled") && (
                          <button type="button" className="btn" style={{ height: 30 }} onClick={() => start(v.id)}>
                            {v.status === "pending" ? t("start_dub") : t("retry")}
                          </button>
                        )}
                      </span>
                      {v.status === "error" && (v.error || v.error_code) && (() => {
                        const failed = jobErrorText(v.error, v.error_code, v.error_params, t);
                        return <div className="small danger-text" title={failed.detail ? t("detail", { d: failed.detail }) : undefined}>
                          {failed.text}</div>;
                      })()}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
