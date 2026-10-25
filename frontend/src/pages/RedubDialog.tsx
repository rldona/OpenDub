import { useEffect, useRef, useState } from "react";
import { api, redub, type EngineChoice, type Video } from "../api";
import { useEngines } from "../App";
import { AUTO_F0_HZ, ENGINES, engineInfo } from "../catalog";
import { Icon } from "../components";
import { useJobs } from "../job";
import { usePrefs } from "../prefs";
import { useDefaultOptions } from "./Library";
import { errorText } from "../errors";

/** Dub the video again: the engine, and whether to keep its translation. Every version is kept. */
export function RedubDialog({ video, watching, onClose, onStarted }: {
  video: Video;
  watching: string | null;
  onClose: () => void;
  onStarted: () => void;
}) {
  const { t } = usePrefs();
  const engines = useEngines();
  const defaults = useDefaultOptions();
  const { refresh } = useJobs();
  const ref = useRef<HTMLDialogElement>(null);
  const [engine, setEngine] = useState<EngineChoice>(() => {
    const other = ENGINES.find((e) => e.id !== watching);
    return other?.id ?? "auto";
  });
  const [keep, setKeep] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [voiceTime, setVoiceTime] = useState<Record<string, number | null>>({});

  useEffect(() => {
    ref.current?.showModal();
  }, []);

  // what each engine did last time on this video: its latest version's voice time and issues
  const lastOf = (id: string) => video.outputs.find((o) => o.engine === id);
  useEffect(() => {
    ENGINES.forEach((e) => {
      const last = video.outputs.find((o) => o.engine === e.id);
      if (!last) return;
      api.version(video.id, last.current ? "latest" : last.version)
        .then((d) => setVoiceTime((m) => ({ ...m, [e.id]: d.stats.voice_seconds })))
        .catch(() => undefined);
    });
  }, [video]);

  const installed = (id: EngineChoice) => engines?.find((e) => e.id === id)?.installed ?? true;
  const f0 = video.reference_f0_hz;
  const autoPick = f0 == null ? null : f0 < AUTO_F0_HZ ? "IndexTTS" : "Chatterbox";
  const label = engine === "auto" ? t("auto") : engineInfo(engine)!.name;

  async function start() {
    try {
      await redub(video.id, defaults, { tts: "clone", engine, keep_translation: keep });
      refresh();
      onStarted();
    } catch (err) {
      setError(errorText(err, t));
    }
  }

  return (
    <dialog ref={ref} className="modal" aria-labelledby="redub-title" onClose={onClose}>
      <div className="stack" style={{ gap: 18 }}>
        <div className="spread" style={{ alignItems: "flex-start", flexWrap: "nowrap" }}>
          <div>
            <h2 id="redub-title" style={{ fontSize: 20 }}>{t("redub_title")}</h2>
            <p className="small muted" style={{ margin: "2px 0 0" }}>{video.title}</p>
          </div>
          <button type="button" className="icon-btn" aria-label={t("close")} onClick={() => ref.current?.close()}><Icon name="close" /></button>
        </div>

        <fieldset style={{ margin: 0, padding: 0, border: 0 }}>
          <legend style={{ padding: 0, marginBottom: 10, fontWeight: 650 }}>{t("engine")}</legend>
          <div className="grid-2">
            <label className="radio-card">
              <input type="radio" name="redub-engine" checked={engine === "auto"} disabled={!installed("auto")} onChange={() => setEngine("auto")} />
              <span className="stack" style={{ gap: 2 }}>
                <span className="title">{t("auto")}</span>
                <span className="small muted">{autoPick ? t("would_pick", { e: autoPick, f0: Math.round(f0!) }) : t("note_auto")}</span>
              </span>
            </label>
            {ENGINES.map((e) => {
              const last = lastOf(e.id);
              const secs = voiceTime[e.id];
              const what = last ? [secs != null ? t("min_n", { m: (secs / 60).toFixed(1) }) : null, t("issues_n", { n: last.issues })]
                .filter(Boolean).join(" · ") : null;
              const ok = installed(e.id);
              return (
                <label key={e.id} className="radio-card" title={ok ? undefined : engines?.find((x) => x.id === e.id)?.setup ?? undefined}>
                  <input type="radio" name="redub-engine" checked={engine === e.id} disabled={!ok} onChange={() => setEngine(e.id)} />
                  <span className="stack" style={{ gap: 2 }}>
                    <span className="title"><span className={`dot ${e.id}`} />{e.name} <span className="small faint" style={{ fontWeight: 400 }}>{e.license}</span></span>
                    <span className="small muted">{t(e.note)}</span>
                    <span className="small muted">
                      {!ok ? t("not_installed") : what ? t("last_time", { what }) : t("never_here")}
                      {watching === e.id ? ` · ${t("watching")}` : ""}
                    </span>
                  </span>
                </label>
              );
            })}
          </div>
        </fieldset>

        <label className="radio-card" style={{ gap: 12 }}>
          <input type="checkbox" checked={keep} onChange={(e) => setKeep(e.target.checked)} style={{ width: 18, height: 18 }} />
          <span className="stack" style={{ gap: 2 }}>
            <span style={{ fontWeight: 650 }}>{t("keep_translation")}</span>
            <span className="small muted">{t("keep_translation_hint")}</span>
          </span>
        </label>

        {error && <p className="error" role="alert">{error}</p>}
        <div className="spread">
          <span className="small muted">{t("all_kept")}</span>
          <div className="row" style={{ gap: 8 }}>
            <button type="button" className="btn" onClick={() => ref.current?.close()}>{t("cancel")}</button>
            <button type="button" className="btn primary" onClick={start}>{t("redub_with", { e: label })}</button>
          </div>
        </div>
      </div>
    </dialog>
  );
}
