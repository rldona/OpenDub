import { useState } from "react";
import { useEngines } from "../App";
import { ENGINES, STOCK_VOICES, type EngineInfo, type VoiceFigures } from "../catalog";
import { percent } from "../format";
import { usePrefs } from "../prefs";

export function Engines() {
  const { t, prefs, set } = usePrefs();
  const status = useEngines();
  return (
    <>
      <div>
        <div className="crumbs">{t("setup")} / {t("engines")}</div>
        <h1>{t("engines")}</h1>
        <p className="muted" style={{ margin: "4px 0 0" }}>{t("engines_intro")}</p>
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(420px, 1fr))", gap: 14 }}>
        {ENGINES.map((e) => (
          <EngineCard key={e.id} engine={e} installed={status?.find((s) => s.id === e.id)?.installed ?? null}
            setup={status?.find((s) => s.id === e.id)?.setup ?? null} />
        ))}
        <section className="card stack engine-card" aria-labelledby="e-edge" style={{ padding: 16, gap: 12 }}>
          <div className="spread">
            <h2 id="e-edge" className="row" style={{ gap: 8 }}><span className="dot edge" />edge-tts</h2>
            <span className="badge">{t("online")}</span>
          </div>
          <div className="small muted">{t("edge_desc")}</div>
          <label className="field small">
            {t("stock_voice")}
            <select className="select" value={prefs.voice} onChange={(e) => set({ voice: e.target.value })}>
              {[...new Set([prefs.voice, ...STOCK_VOICES])].map((v) => <option key={v}>{v}</option>)}
            </select>
          </label>
        </section>
      </div>
    </>
  );
}

function EngineCard({ engine: e, installed, setup }: { engine: EngineInfo; installed: boolean | null; setup: string | null }) {
  const { t, prefs } = usePrefs();
  const [copied, setCopied] = useState(false);
  const row = (label: string, v: VoiceFigures) => (
    <tr>
      <th scope="row">{label}</th>
      <td>{percent(v.cer, prefs.lang)}</td>
      <td>{v.p_es.toFixed(2)}</td>
      <td>{v.ecapa.toFixed(2)}</td>
      <td>{v.cps.toLocaleString(prefs.lang)}</td>
    </tr>
  );
  return (
    <section className="card stack engine-card" aria-labelledby={`e-${e.id}`} style={{ padding: 16, gap: 12 }}>
      <div className="spread">
        <h2 id={`e-${e.id}`} className="row" style={{ gap: 8 }}><span className={`dot ${e.id}`} />{e.name}</h2>
        {installed === false ? <span className="badge warning">{t("not_installed")}</span>
          : installed ? <span className="badge done">{t("ready")}</span> : null}
      </div>
      <div className="small muted">{e.license} · {e.inside ? t("runs_inside") : t("own_venv")} · {t(e.note)}</div>
      <table className="num">
        <thead>
          <tr><th scope="col">{t("voice")}</th><th scope="col">{t("errors")}</th><th scope="col">{t("spanish_p")}</th><th scope="col">{t("likeness")}</th><th scope="col">{t("chars_s")}</th></tr>
        </thead>
        <tbody>
          {row(t("male"), e.male)}
          {row(t("female"), e.female)}
        </tbody>
      </table>
      <div className="row small muted" style={{ gap: "6px 16px" }}>
        <span>{t("rtf", { v: e.rtf })}</span>
        <span>{t("vram", { v: e.vram.toLocaleString(prefs.lang) })}</span>
        <span>{t("fits", { n: e.fits })}</span>
      </div>
      {installed === false && setup && (
        <div className="row" style={{ gap: 8, flexWrap: "nowrap" }}>
          <code className="cmd">{setup}</code>
          <button type="button" className="btn" style={{ height: 36 }}
            onClick={() => navigator.clipboard?.writeText(setup).then(() => setCopied(true)).catch(() => undefined)}>
            {copied ? t("copied") : t("copy")}
          </button>
        </div>
      )}
    </section>
  );
}
