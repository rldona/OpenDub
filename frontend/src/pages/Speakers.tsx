import { useState } from "react";
import { api, type Speaker, type Translation } from "../api";
import { engineShort } from "../catalog";
import { PlayIcon } from "../components";
import { usePrefs } from "../prefs";

/** "Andy" when named, else the diarization's letter. */
export function speakerName(speakers: Speaker[], id: string | null): string {
  const s = speakers.find((x) => x.id === id);
  return s?.name || (id ?? "?");
}

/** A speaker's color dot and name, as each sentence shows it. */
export function SpeakerTag({ speakers, id }: { speakers: Speaker[]; id: string | null }) {
  return (
    <span className="speaker-tag">
      <span className={`spk spk-${id ?? "none"}`} aria-hidden="true" />
      {speakerName(speakers, id)}
    </span>
  );
}

/** Who speaks in a video dubbed with several voices: rename, hear and merge them. */
export function SpeakersCard({ id, speakers, busy, onSpeakers, onTranslation }: {
  id: string;
  speakers: Speaker[];
  busy: boolean;
  onSpeakers: (s: Speaker[]) => void;
  onTranslation: (t: Translation) => void;
}) {
  const { t } = usePrefs();
  const [note, setNote] = useState<string | null>(null);
  const [audio] = useState(() => new Audio());

  async function rename(speaker: Speaker, name: string) {
    if ((speaker.name ?? "") === name.trim()) return;
    try {
      onSpeakers(await api.renameSpeaker(id, speaker.id, name));
    } catch (err) {
      setNote((err as Error).message);
    }
  }

  async function merge(speaker: Speaker, into: string) {
    if (!confirm(t("merge_confirm", { a: speakerName(speakers, speaker.id), b: speakerName(speakers, into) }))) return;
    try {
      const r = await api.mergeSpeaker(id, speaker.id, into);
      onSpeakers(r.speakers);
      onTranslation(r.translation);
      setNote(t("merged_n", { n: r.moved }));
    } catch (err) {
      setNote((err as Error).message);
    }
  }

  const voiceText = (s: Speaker) => {
    const v = s.voice;
    if (!v) return t("voice_not_yet");
    return v.engine === "edge" ? t("voice_stock_n", { v: (v.voice ?? "").replace(/^es-..-|Neural$/g, "") })
      : t("voice_cloned_n", { e: engineShort(v.engine) });
  };

  return (
    <section className="card stack" aria-labelledby="speakers" style={{ padding: 16, gap: 12 }}>
      <div className="spread">
        <h2 id="speakers" style={{ fontSize: 15 }}>{t("speakers")} <span className="small faint" style={{ fontWeight: 400 }}>· {t("speakers_hint")}</span></h2>
        {note && <span className="small muted" role="status">{note}</span>}
      </div>
      <div className="grid-2" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(240px, 1fr))", gap: 10 }}>
        {speakers.map((s) => (
          <div key={s.id} className="speaker-card">
            <div className="row" style={{ gap: 8, flexWrap: "nowrap" }}>
              <span className={`spk spk-${s.id}`} aria-hidden="true" />
              <label style={{ flex: 1, minWidth: 0 }}>
                <span className="sr-only">{t("speaker_name_n", { s: s.id })}</span>
                <input className="input" defaultValue={s.name ?? ""} placeholder={t("speaker_n", { s: s.id })}
                  maxLength={60} onBlur={(e) => void rename(s, e.target.value)}
                  onKeyDown={(e) => { if (e.key === "Enter") (e.target as HTMLInputElement).blur(); }} />
              </label>
              {s.sample && (
                <button type="button" className="round-btn" aria-label={t("hear_speaker", { s: speakerName(speakers, s.id) })}
                  onClick={() => { audio.pause(); audio.src = s.sample!; void audio.play(); }}><PlayIcon /></button>
              )}
            </div>
            <div className="small muted">
              {[s.gender ? t(`gender_${s.gender}`) : null, s.seconds != null ? t("min_n", { m: (s.seconds / 60).toFixed(1) }) : null,
                t("sentences_n", { n: s.sentences })].filter(Boolean).join(" · ")}
            </div>
            <div className="small">{voiceText(s)}</div>
            {speakers.length > 1 && !busy && (
              <label className="small muted row" style={{ gap: 6 }}>
                {t("merge_into")}
                <select className="select" value="" style={{ flex: 1, minWidth: 0, padding: "4px 8px" }}
                  onChange={(e) => e.target.value && void merge(s, e.target.value)}>
                  <option value="">—</option>
                  {speakers.filter((o) => o.id !== s.id).map((o) => (
                    <option key={o.id} value={o.id}>{speakerName(speakers, o.id)}</option>
                  ))}
                </select>
              </label>
            )}
          </div>
        ))}
      </div>
    </section>
  );
}
