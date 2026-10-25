import { useEffect, useState } from "react";
import { useEngines } from "../App";
import { api, type EngineChoice, type Style } from "../api";
import { ENGINES } from "../catalog";
import { Logo } from "../components";
import { usePrefs, type Accent, type Theme } from "../prefs";
import { cleanStyle, sameStyle, StyleEditor } from "./StyleEditor";

const ACCENTS: { id: Accent; color: string }[] = [
  { id: "violet", color: "#8b7cf6" }, { id: "coral", color: "#ff7a59" }, { id: "lime", color: "#c6f05a" },
];

export function Preferences() {
  const { t, prefs, set } = usePrefs();
  const engines = useEngines();
  const installed = (id: EngineChoice) => engines?.find((e) => e.id === id)?.installed ?? true;
  return (
    <div className="stack" style={{ gap: 18, maxWidth: 900 }}>
      <div>
        <div className="crumbs">{t("setup")} / {t("preferences")}</div>
        <h1>{t("preferences")}</h1>
        <p className="muted" style={{ margin: "4px 0 0" }}>{t("prefs_intro")}</p>
      </div>

      <section className="card stack" aria-labelledby="appearance" style={{ gap: 18 }}>
        <h2 id="appearance">{t("appearance")}</h2>
        <div className="field">
          <span id="theme-label">{t("theme")}</span>
          <div className="segmented" role="radiogroup" aria-labelledby="theme-label" style={{ width: "fit-content" }}>
            {(["system", "dark", "light"] as Theme[]).map((th) => (
              <button key={th} type="button" role="radio" aria-checked={prefs.theme === th} onClick={() => set({ theme: th })}>
                {t(`theme_${th}`)}
              </button>
            ))}
          </div>
        </div>
        <fieldset style={{ margin: 0, padding: 0, border: 0 }}>
          <legend className="muted" style={{ padding: 0, marginBottom: 8 }}>{t("accent")}</legend>
          <div className="grid-2" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))" }}>
            {ACCENTS.map((a) => (
              <label key={a.id} className="swatch-card">
                <span className="spread" style={{ flexWrap: "nowrap" }}>
                  <span data-accent-preview={a.id} style={{ ["--accent" as string]: a.color, display: "flex" }}><Logo size={34} /></span>
                  <input type="radio" name="accent" checked={prefs.accent === a.id} onChange={() => set({ accent: a.id })}
                    style={{ accentColor: "var(--accent)", width: 18, height: 18, margin: 0 }} />
                </span>
                <span style={{ fontWeight: 650 }}>
                  {t(a.id)}{a.id === "violet" && <span className="muted" style={{ fontWeight: 400 }}> · {t("default_tag")}</span>}
                </span>
                <span className="bar" style={{ background: a.color }} />
              </label>
            ))}
          </div>
        </fieldset>
        <label className="field" style={{ maxWidth: 320 }}>
          {t("language")}
          <select className="select" value={prefs.lang} onChange={(e) => set({ lang: e.target.value as "en" | "es" })}>
            <option value="en">English</option>
            <option value="es">Español</option>
          </select>
        </label>
      </section>

      <section className="card stack" aria-labelledby="defaults" style={{ gap: 16 }}>
        <h2 id="defaults">{t("new_dubs")}</h2>
        <div className="grid-2">
          <label className="field">
            {t("voice")}
            <select className="select" value={prefs.tts} onChange={(e) => set({ tts: e.target.value as "clone" | "edge" })}>
              <option value="clone">{t("voice_clone")}</option>
              <option value="edge">{t("voice_stock")}</option>
            </select>
          </label>
          <label className="field">
            {t("engine")}
            <select className="select" value={prefs.engine} onChange={(e) => set({ engine: e.target.value as EngineChoice })}>
              <option value="auto" disabled={!installed("auto")}>{t("auto")}</option>
              {ENGINES.map((e) => <option key={e.id} value={e.id} disabled={!installed(e.id)}>{e.name}</option>)}
            </select>
          </label>
          <label className="row" style={{ gap: 10, cursor: "pointer" }}>
            <input type="checkbox" checked={prefs.separate} style={{ width: 18, height: 18, accentColor: "var(--accent)" }}
              onChange={(e) => set({ separate: e.target.checked, bgVolume: e.target.checked ? 0 : -15 })} />
            {t("keep_music")}
          </label>
          <label className="field">
            {t("bg_volume")} · {prefs.bgVolume} dB
            <input type="range" min={-30} max={6} step={1} value={prefs.bgVolume} style={{ accentColor: "var(--accent)" }}
              onChange={(e) => set({ bgVolume: Number(e.target.value) })} />
          </label>
        </div>
      </section>

      <GlobalStyle />
    </div>
  );
}

/** work/style.json: on the server, for every video (unlike the rest of this page). */
function GlobalStyle() {
  const { t } = usePrefs();
  const [saved, setSaved] = useState<Style | null>(null);
  const [draft, setDraft] = useState<Style | null>(null);
  const [note, setNote] = useState<string | null>(null);
  useEffect(() => {
    api.style().then((s) => { setSaved(s); setDraft(s); }).catch((e) => setNote((e as Error).message));
  }, []);
  const changed = !!saved && !!draft && !sameStyle(saved, draft);

  async function save() {
    try {
      const s = await api.saveStyle(cleanStyle(draft!));
      setSaved(s);
      setDraft(s);
      setNote(t("style_saved"));
    } catch (err) {
      setNote((err as Error).message);
    }
  }

  return (
    <section className="card stack" aria-labelledby="style" style={{ gap: 16 }}>
      <div>
        <h2 id="style">{t("translation_style")}</h2>
        <p className="small muted" style={{ margin: "4px 0 0" }}>{t("translation_style_intro")}</p>
      </div>
      {draft ? <StyleEditor idPrefix="global" value={draft} onChange={(s) => { setDraft(s); setNote(null); }} /> : <p className="muted">…</p>}
      <div className="spread">
        <span className="small muted" role="status">{note}</span>
        <div className="row" style={{ gap: 8 }}>
          <button type="button" className="btn" disabled={!changed} onClick={() => { setDraft(saved); setNote(null); }}>{t("discard")}</button>
          <button type="button" className="btn primary" disabled={!changed} onClick={() => void save()}>{t("save")}</button>
        </div>
      </div>
    </section>
  );
}
