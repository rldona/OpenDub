import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, media, type Issue, type Translation, type Video, type VersionDetail } from "../api";
import { engineShort } from "../catalog";
import { PlayIcon, StatusBadge } from "../components";
import { duration, seconds, when } from "../format";
import type { Key } from "../i18n";
import { useJobs } from "../job";
import { usePrefs } from "../prefs";
import { RedubDialog } from "./RedubDialog";

type Filter = "all" | "issues" | "edited";

/** One line saying what happened to a clip, in the page's language (overflow.log is English). */
export function issueText(issue: Issue, t: (k: Key, v?: Record<string, string | number>) => string): string {
  switch (issue.kind) {
    case "fallback":
      return t("i_fallback", { text: issue.text ?? "" });
    case "floor":
      return t("i_floor", { f: /factor ([\d.]+)/.exec(issue.message)?.[1] ?? "?" });
    case "overflow":
      return t("i_overflow", { s: /\(\+([\d.]+)s\)/.exec(issue.message)?.[1] ?? "?" });
    case "abnormal":
      return t("i_abnormal");
    case "delayed":
      return t("i_delayed");
    case "repaired": {
      const how = issue.message.includes("seed+1") ? t("how_seed") : issue.message.includes("shortened")
        ? t("how_shortened") : issue.message.includes("fixed reference") ? t("how_fixed") : issue.message.split(": ").pop()!;
      return t("i_repaired", { how });
    }
  }
}

export function issueClass(issue: Issue): string {
  return issue.kind === "fallback" ? "danger-text" : issue.kind === "repaired" || issue.kind === "delayed" ? "muted" : "warn-text";
}

export function VideoPage({ id }: { id: string }) {
  const { t, prefs } = usePrefs();
  const { finished, job } = useJobs();
  const [video, setVideo] = useState<Video | null | undefined>(undefined);
  const [translation, setTranslation] = useState<Translation | null>(null);
  const [version, setVersion] = useState<string | null>(null); // null: the latest
  const [detail, setDetail] = useState<VersionDetail | null>(null);
  const [edits, setEdits] = useState<Map<number, string>>(new Map());
  const [filter, setFilter] = useState<Filter>("all");
  const [note, setNote] = useState<string | null>(null);
  const [dialog, setDialog] = useState(false);
  const [time, setTime] = useState(0);
  const player = useRef<HTMLVideoElement>(null);

  const load = useCallback(async () => {
    const v = await api.video(id).catch(() => null);
    setVideo(v);
    if (v) setTranslation(await api.translation(id).catch(() => null));
  }, [id]);
  useEffect(() => {
    void load();
  }, [load, finished]);

  const versions = useMemo(() => video?.outputs ?? [], [video]);
  const selected = version && versions.some((o) => o.version === version) ? version : null;
  useEffect(() => {
    if (!video || !versions.length) {
      setDetail(null);
      return;
    }
    api.version(id, selected ?? "latest").then(setDetail).catch(() => setDetail(null));
  }, [id, video, versions, selected]);

  const busy = !!job && job.id === id && (job.status === "running" || job.status === "queued");
  const issuesById = useMemo(() => {
    const map = new Map<number, Issue[]>();
    detail?.issues.forEach((i) => map.set(i.id, [...(map.get(i.id) ?? []), i]));
    return map;
  }, [detail]);

  if (video === undefined) return <p className="muted">…</p>;
  if (video === null) {
    return (
      <>
        <a href="#/">← {t("library")}</a>
        <p>{t("not_found")}</p>
      </>
    );
  }

  const seek = (start: number | null) => {
    const v = player.current;
    if (!v || start == null) return;
    v.currentTime = Math.max(0, start - 0.2);
    void v.play();
    v.scrollIntoView({ block: "nearest", behavior: "smooth" });
  };

  async function save(): Promise<boolean> {
    if (!edits.size) return true;
    try {
      setTranslation(await api.saveTranslation(id, [...edits].map(([sid, text]) => ({ id: sid, text }))));
      setEdits(new Map());
      setNote(t("saved_ok"));
      return true;
    } catch (err) {
      setNote((err as Error).message);
      return false;
    }
  }

  async function remove() {
    if (!detail || detail.current) return;
    if (!confirm(t("confirm_delete", { e: engineShort(detail.engine), d: when(detail.date, prefs.lang) }))) return;
    try {
      const r = await api.deleteVersion(id, detail.version);
      setVideo({ ...video!, outputs: r.outputs });
      setVersion(null);
    } catch (err) {
      alert((err as Error).message);
    }
  }

  const segments = translation?.segments ?? [];
  const rows = segments.filter((s) => filter === "all" || (filter === "issues" ? issuesById.has(s.id) : s.edited || edits.has(s.id)));
  const editedCount = segments.filter((s) => s.edited || edits.has(s.id)).length;
  const length = video.duration ?? 0;

  return (
    <>
      <div className="page-head">
        <div style={{ minWidth: 0 }}>
          <div className="crumbs"><a href="#/">{t("library")}</a> / {video.title ?? id}</div>
          <h1>{video.title ?? id}</h1>
          <div className="small muted">
            {[duration(video.duration), video.clips ? t("segments_n", { n: video.clips }) : null,
              video.reference_f0_hz ? t("ref_voice", { f0: Math.round(video.reference_f0_hz) }) : null].filter(Boolean).join(" · ")}
            {" · "}<a href={`https://www.youtube.com/watch?v=${id}`} target="_blank" rel="noreferrer">{t("on_youtube")}</a>
          </div>
        </div>
        <div className="row">
          {versions.length > 1 && <a className="btn" href={`#/compare/${id}`}>{t("compare_btn")}</a>}
          {translation && <button type="button" className="btn primary" disabled={busy} onClick={() => setDialog(true)}>{t("redub_btn")}</button>}
        </div>
      </div>

      {busy && <div className="notice">{t("busy")}</div>}
      {!busy && translation?.needs_regeneration && !edits.size && <div className="notice">{t("needs_regen")}</div>}

      <div className="row" style={{ alignItems: "flex-start", gap: 20 }}>
        <div className="stack" style={{ flex: "999 1 560px", minWidth: 0, gap: 10 }}>
          {versions.length ? (
            <div className="player">
              <video ref={player} key={selected ?? "latest"} controls preload="metadata" src={media.video(id, selected)}
                onTimeUpdate={(e) => setTime(e.currentTarget.currentTime)} />
            </div>
          ) : (
            <div className="stack">
              <img className="thumb" style={{ width: "100%", borderRadius: 12 }} src={media.thumbnail(id)} alt="" />
              <div className="row"><StatusBadge status={video.status} /><span className="muted">{t("not_dubbed")}</span></div>
            </div>
          )}
          {detail && length > 0 && detail.issues.length > 0 && (
            <div className="stack" style={{ gap: 6 }} role="group" aria-label={t("timeline")}>
              <div className="timeline">
                <span className="head" style={{ left: `${(100 * time) / length}%` }} />
                {detail.issues.filter((i) => i.start != null).map((i) => (
                  <button key={`${i.kind}-${i.id}`} type="button" className={`mark-${i.kind}`}
                    style={{ left: `${(100 * i.start!) / length}%` }} title={`#${i.id} · ${duration(i.start)} · ${issueText(i, t)}`}
                    aria-label={`#${i.id} · ${duration(i.start)} · ${issueText(i, t)}`} onClick={() => seek(i.start)} />
                ))}
              </div>
              <div className="legend">
                <span><i className="mark-fallback" />{t("legend_fallback")}</span>
                <span><i className="mark-floor" />{t("legend_floor")}</span>
                <span><i className="mark-repaired" />{t("legend_repaired")}</span>
                <span style={{ marginLeft: "auto" }}>{t("timeline_hint")}</span>
              </div>
            </div>
          )}
        </div>

        {versions.length > 0 && (
          <aside className="card stack" style={{ flex: "1 1 300px", minWidth: 0, padding: 16, gap: 12 }} aria-labelledby="versions">
            <h2 id="versions" style={{ fontSize: 14 }}>{t("versions")} <span className="faint" style={{ fontWeight: 400 }}>· {t("kept_n", { n: versions.length })}</span></h2>
            <div className="stack" role="radiogroup" aria-label={t("versions")} style={{ gap: 6 }}>
              {versions.map((o) => {
                const on = selected ? o.version === selected : o.current;
                return (
                  <button key={o.version} type="button" role="radio" aria-checked={on} className="version"
                    onClick={() => setVersion(o.current ? null : o.version)}>
                    <span className={`dot ${o.engine}`} />
                    <span style={{ flex: 1 }}>
                      {engineShort(o.engine)}{" "}
                      <span className={on ? "" : "faint"} style={on ? { color: "var(--accent-text)" } : undefined}>
                        · {when(o.date, prefs.lang)}{o.current ? ` · ${t("latest")}` : ""}{on ? ` · ${t("watching")}` : ""}
                      </span>
                    </span>
                    <span className={`small ${o.issues ? "warn-text" : "ok-text"}`}>{o.issues}</span>
                  </button>
                );
              })}
            </div>
            {detail && (
              <dl className="stats" style={{ paddingTop: 12, borderTop: "1px solid var(--border)" }}>
                <dt>{t("voice_phase")}</dt><dd>{detail.stats.voice_seconds != null ? t("min_n", { m: (detail.stats.voice_seconds / 60).toFixed(1) }) : "—"}</dd>
                <dt>{t("sped_shortened")}</dt><dd>{detail.stats.sped_up} · {detail.stats.shortened ?? "—"}</dd>
                <dt>{t("floor_redone")}</dt><dd>{detail.stats.below_floor} · {detail.stats.redone}</dd>
                <dt>{t("spoken_edge")}</dt><dd className={detail.stats.edge ? "danger-text" : ""}>{detail.stats.edge}</dd>
              </dl>
            )}
            <div className="grid-2" style={{ gridTemplateColumns: "repeat(2, minmax(0, 1fr))", gap: 8 }}>
              <a className="btn" href={media.video(id, selected)} download={`${id}.es${selected ? "." + selected : ""}.mp4`}>{t("download")}</a>
              <button type="button" className="btn danger" disabled={!detail || detail.current} onClick={remove}
                title={detail?.current ? t("delete_latest") : undefined}>{t("delete")}</button>
            </div>
          </aside>
        )}
      </div>

      {translation && (
        <section className="stack" aria-labelledby="translation" style={{ gap: 12 }}>
          <div className="spread">
            <h2 id="translation">{t("translation")}</h2>
            <div className="row" role="group" aria-label={t("show")} style={{ gap: 6 }}>
              <button type="button" className="chip" aria-pressed={filter === "all"} onClick={() => setFilter("all")}>{t("filter_all", { n: segments.length })}</button>
              <button type="button" className="chip warn" aria-pressed={filter === "issues"} onClick={() => setFilter("issues")}>{t("filter_issues", { n: issuesById.size })}</button>
              <button type="button" className="chip" aria-pressed={filter === "edited"} onClick={() => setFilter("edited")}>{t("filter_edited", { n: editedCount })}</button>
            </div>
          </div>
          <div className="table-box">
            <table className="data" style={{ minWidth: 860 }}>
              <thead>
                <tr>
                  <th scope="col" style={{ width: 64 }}>#</th>
                  <th scope="col" style={{ width: "30%" }}>{t("col_original")}</th>
                  <th scope="col">{t("col_spanish")}</th>
                  <th scope="col" style={{ width: 90, textAlign: "right" }}>{t("col_slot")}</th>
                  {detail && <th scope="col" style={{ width: 220 }}>{t("col_in_version")}</th>}
                </tr>
              </thead>
              <tbody>
                {rows.map((s) => {
                  const text = edits.get(s.id) ?? s.text;
                  const chars = [...text].length;
                  const over = !!s.max_chars && chars > s.max_chars * 1.25;
                  const found = issuesById.get(s.id) ?? [];
                  return (
                    <tr key={s.id} className={over ? "over" : undefined}>
                      <td className="small faint">{s.id}<br />{duration(s.start)}{s.edited && <span title={t("edited")} aria-label={t("edited")} style={{ color: "var(--accent-text)" }}> ✎</span>}</td>
                      <td className="muted">{s.original}</td>
                      <td className="text">
                        <label>
                          <span className="sr-only">{t("spanish_n", { n: s.id })}</span>
                          <textarea className="input" rows={Math.min(4, Math.max(1, Math.ceil(chars / 60)))} value={text} disabled={busy}
                            style={edits.has(s.id) ? { borderColor: "var(--accent)" } : undefined}
                            onChange={(e) => {
                              const next = new Map(edits);
                              if (e.target.value === s.text) next.delete(s.id); else next.set(s.id, e.target.value);
                              setEdits(next);
                              setNote(null);
                            }} />
                        </label>
                        {edits.has(s.id) && <div className="small" style={{ color: "var(--accent-text)" }}>{t("edited_unsaved")}</div>}
                      </td>
                      <td className="small muted num" style={{ textAlign: "right" }}>
                        {seconds(s.slot, prefs.lang)}<br />
                        <span className={over ? "warn-text" : ""}>{s.max_chars ? `${chars} / ${s.max_chars}` : chars}</span>
                      </td>
                      {detail && (
                        <td>
                          {found.length ? (
                            <span className="row" style={{ gap: 8, flexWrap: "nowrap" }}>
                              <button type="button" className="round-btn" aria-label={t("listen", { n: s.id })} onClick={() => seek(s.start)}><PlayIcon /></button>
                              <span className="small stack" style={{ gap: 2 }}>
                                {found.map((i) => <span key={i.kind} className={issueClass(i)}>{issueText(i, t)}</span>)}
                              </span>
                            </span>
                          ) : <span className="faint">—</span>}
                        </td>
                      )}
                    </tr>
                  );
                })}
                {rows.length === 0 && (
                  <tr><td colSpan={5} className="muted">{t("no_rows")}</td></tr>
                )}
              </tbody>
            </table>
          </div>
        </section>
      )}

      {(edits.size > 0 || note) && (
        <div className="savebar" role="region" aria-label={t("save")}>
          <span>
            {edits.size > 0 ? (
              <>
                <strong>{edits.size === 1 ? t("unsaved_1") : t("unsaved_n", { n: edits.size })}.</strong>{" "}
                <span className="muted">{t("saved_hint")}</span>
              </>
            ) : <span className="muted">{note}</span>}
          </span>
          {edits.size > 0 ? (
            <div className="row" style={{ gap: 8 }}>
              <button type="button" className="btn" onClick={() => { setEdits(new Map()); setNote(null); }}>{t("discard")}</button>
              <button type="button" className="btn solid" onClick={() => void save()}>{t("save")}</button>
              <button type="button" className="btn primary" disabled={busy}
                onClick={async () => { if (await save()) setDialog(true); }}>{t("save_redub")}</button>
            </div>
          ) : (
            <button type="button" className="btn primary" disabled={busy} onClick={() => setDialog(true)}>{t("redub_btn")}</button>
          )}
        </div>
      )}

      {dialog && (
        <RedubDialog video={video} watching={detail?.engine ?? null}
          onClose={() => setDialog(false)}
          onStarted={() => { setDialog(false); setNote(null); void load(); }} />
      )}
    </>
  );
}
