import { useEffect, useMemo, useRef, useState } from "react";
import { api, media, type Clip, type Issue, type Video, type VersionDetail } from "../api";
import { engineShort } from "../catalog";
import { PauseIcon, PlayIcon } from "../components";
import { duration, when } from "../format";
import { useJobs } from "../job";
import { usePrefs } from "../prefs";
import { issueClass, issueText } from "./Video";

type Side = "a" | "b";

export function Compare({ id }: { id: string | null }) {
  const { t, prefs } = usePrefs();
  const { finished } = useJobs();
  const [videos, setVideos] = useState<Video[] | null>(null);
  useEffect(() => {
    api.videos().then(setVideos).catch(() => setVideos([]));
  }, [finished]);

  const comparable = (videos ?? []).filter((v) => v.outputs.length > 1);
  const video = comparable.find((v) => v.id === id) ?? comparable[0];
  if (!videos) return <p className="muted">…</p>;
  return (
    <>
      <div className="page-head">
        <div>
          <div className="crumbs">{t("workspace")} / {t("compare")}</div>
          <h1>{t("compare_title")}</h1>
        </div>
        {video && (
          <label className="field small" style={{ minWidth: 340 }}>
            {t("video")}
            <select className="select" value={video.id} onChange={(e) => { location.hash = `#/compare/${e.target.value}`; }}>
              {comparable.map((v) => <option key={v.id} value={v.id}>{v.title ?? v.id} · {t("kept_n", { n: v.outputs.length })}</option>)}
            </select>
          </label>
        )}
      </div>
      {video ? <Comparison key={video.id} video={video} lang={prefs.lang} /> : <p className="muted">{t("need_two")}</p>}
    </>
  );
}

function Comparison({ video, lang }: { video: Video; lang: "en" | "es" }) {
  const { t } = usePrefs();
  const versions = video.outputs;
  const [a, setA] = useState(versions[0].version);
  const [b, setB] = useState(versions[1].version);
  const [hear, setHear] = useState<Side>("a");
  const [playing, setPlaying] = useState(false);
  const [time, setTime] = useState(0);
  const [details, setDetails] = useState<Record<Side, VersionDetail | null>>({ a: null, b: null });
  const refs = { a: useRef<HTMLVideoElement>(null), b: useRef<HTMLVideoElement>(null) };

  const ref = (v: string) => (versions.find((o) => o.version === v)?.current ? "latest" : v);
  useEffect(() => {
    api.version(video.id, ref(a)).then((d) => setDetails((x) => ({ ...x, a: d }))).catch(() => undefined);
  }, [video.id, a]); 
  useEffect(() => {
    api.version(video.id, ref(b)).then((d) => setDetails((x) => ({ ...x, b: d }))).catch(() => undefined);
  }, [video.id, b]); 

  // A leads; B follows it, and only the side being heard has sound
  useEffect(() => {
    if (refs.a.current) refs.a.current.muted = hear !== "a";
    if (refs.b.current) refs.b.current.muted = hear !== "b";
  }, [hear, a, b]); 
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.target instanceof HTMLInputElement || e.target instanceof HTMLSelectElement || e.target instanceof HTMLTextAreaElement) return;
      if (e.key === "a" || e.key === "A") setHear("a");
      if (e.key === "b" || e.key === "B") setHear("b");
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const both = (fn: (v: HTMLVideoElement) => void) => [refs.a.current, refs.b.current].forEach((v) => v && fn(v));
  const toggle = () => {
    if (playing) both((v) => v.pause());
    else {
      if (refs.b.current && refs.a.current) refs.b.current.currentTime = refs.a.current.currentTime;
      both((v) => void v.play());
    }
  };
  const seek = (start: number) => both((v) => {
    v.currentTime = Math.max(0, start - 0.2);
    void v.play();
  });
  const follow = () => {
    const lead = refs.a.current;
    const other = refs.b.current;
    if (!lead || !other) return;
    setTime(lead.currentTime);
    if (Math.abs(other.currentTime - lead.currentTime) > 0.25) other.currentTime = lead.currentTime;
    if (lead.paused !== other.paused) {
      if (lead.paused) other.pause(); else void other.play();
    }
  };

  const diffs = useMemo(() => differences(details.a, details.b), [details]);

  const player = (side: Side, value: string, set: (v: string) => void) => (
    <div className="stack" style={{ gap: 8 }}>
      <label className="row small muted" style={{ flexWrap: "nowrap" }}>
        <span className={`ab ${hear === side ? "on" : ""}`}>{side.toUpperCase()}</span>
        <select className="select" style={{ flex: 1 }} value={value} onChange={(e) => set(e.target.value)}>
          {versions.map((o) => (
            <option key={o.version} value={o.version}>{engineShort(o.engine)} · {when(o.date, lang)}{o.current ? ` · ${t("latest")}` : ""}</option>
          ))}
        </select>
      </label>
      <div className="player" style={{ outline: hear === side ? "2px solid var(--accent)" : "none" }}>
        <video ref={refs[side]} key={value} preload="metadata" src={media.video(video.id, versions.find((o) => o.version === value)?.current ? null : value)}
          muted={hear !== side} controls={side === "a"}
          onPlay={() => side === "a" && setPlaying(true)} onPause={() => side === "a" && setPlaying(false)}
          onTimeUpdate={side === "a" ? follow : undefined} onSeeked={side === "a" ? follow : undefined} />
        <span className="badge" style={{ position: "absolute", top: 10, left: 10, background: hear === side ? "var(--accent)" : "rgba(0,0,0,0.6)", color: hear === side ? "var(--on-accent)" : "#fff" }}>
          {hear === side ? t("hearing") : t("muted")}
        </span>
      </div>
    </div>
  );

  const stat = (k: keyof VersionDetail["stats"], d: VersionDetail | null) => {
    const v = d?.stats[k];
    if (v == null) return "—";
    return k === "voice_seconds" ? t("min_n", { m: (v / 60).toFixed(1) }) : String(v);
  };
  const rows: [string, keyof VersionDetail["stats"]][] = [
    [t("voice_phase"), "voice_seconds"], [t("st_shortened"), "shortened"], [t("st_floor"), "below_floor"],
    [t("st_redone"), "redone"], [t("st_sped"), "sped_up"], [t("spoken_edge"), "edge"],
  ];

  return (
    <>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(380px, 1fr))", gap: 16 }}>
        {player("a", a, setA)}
        {player("b", b, setB)}
      </div>
      <div className="card row" style={{ padding: "12px 14px", gap: 12 }}>
        <button type="button" className="round-btn" style={{ width: 44, height: 44, background: "var(--text)", color: "var(--bg)", border: 0 }}
          aria-label={playing ? t("pause_both") : t("play_both")} onClick={toggle}>
          {playing ? <PauseIcon size={18} /> : <PlayIcon size={18} />}
        </button>
        <span className="mono small muted">{duration(time)} / {duration(video.duration)}</span>
        <div className="segmented accent" role="group" aria-label={t("hear")}>
          <button type="button" aria-pressed={hear === "a"} onClick={() => setHear("a")}>{t("hear_a")}</button>
          <button type="button" aria-pressed={hear === "b"} onClick={() => setHear("b")}>{t("hear_b")}</button>
        </div>
        <span className="small muted">{t("sync_hint")}</span>
      </div>
      <div className="row" style={{ alignItems: "flex-start", gap: 16 }}>
        <section className="card" style={{ flex: "1 1 320px", minWidth: 0, padding: 16 }} aria-labelledby="fitted">
          <h2 id="fitted" style={{ fontSize: 15, marginBottom: 8 }}>{t("fitted")}</h2>
          <table className="num" style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead>
              <tr className="small faint" style={{ textAlign: "right" }}>
                <th scope="col" />
                <th scope="col" style={{ fontWeight: 500, padding: "4px 8px" }}>A · {engineShort(details.a?.engine)}</th>
                <th scope="col" style={{ fontWeight: 500 }}>B · {engineShort(details.b?.engine)}</th>
              </tr>
            </thead>
            <tbody style={{ textAlign: "right" }}>
              {rows.map(([label, k]) => {
                const va = details.a?.stats[k];
                const vb = details.b?.stats[k];
                const better = (x: number | null | undefined, y: number | null | undefined) => x != null && y != null && x < y;
                return (
                  <tr key={k} style={{ borderTop: "1px solid var(--border)" }}>
                    <th scope="row" style={{ textAlign: "left", fontWeight: 400, padding: "6px 0" }} className="muted">{label}</th>
                    <td style={{ padding: "6px 8px" }} className={better(va, vb) ? "ok-text" : ""}>{stat(k, details.a)}</td>
                    <td className={better(vb, va) ? "ok-text" : ""}>{stat(k, details.b)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </section>
        <section className="card stack" style={{ flex: "999 1 480px", minWidth: 0, padding: 16, gap: 8 }} aria-labelledby="differ">
          <h2 id="differ" style={{ fontSize: 15 }}>{t("differ")} <span className="small faint" style={{ fontWeight: 400 }}>· {t("jump_hint")}</span></h2>
          {details.a && details.b && diffs.length === 0 && <p className="muted" style={{ margin: 0 }}>{t("no_diff")}</p>}
          {diffs.slice(0, 200).map((d) => (
            <button key={d.id} type="button" className="diff-row" onClick={() => seek(d.start)}>
              <span className="faint">#{d.id}<br />{duration(d.start)}</span>
              <Side_ side={d.a} />
              <Side_ side={d.b} />
            </button>
          ))}
        </section>
      </div>
    </>
  );
}

interface SideDiff {
  issues: Issue[];
  tempo: number | null; // atempo, when the clip was sped up
  text: string | null; // shown when the two sides said different things
}

function Side_({ side }: { side: SideDiff }) {
  const { t } = usePrefs();
  return (
    <span className="small">
      {side.issues.map((i) => <span key={i.kind} className={issueClass(i)} style={{ display: "block" }}>{issueText(i, t)}</span>)}
      {side.tempo != null && <span className="muted" style={{ display: "block" }}>{t("d_atempo", { t: side.tempo.toFixed(2) })}</span>}
      {side.text && <span style={{ display: "block" }}>{side.text}</span>}
      {!side.issues.length && side.tempo == null && !side.text && <span className="faint">{t("as_planned")}</span>}
    </span>
  );
}

/** Segments the two versions fitted differently: issues on either side, or different spoken text. */
function differences(a: VersionDetail | null, b: VersionDetail | null) {
  if (!a || !b) return [];
  const byId = (d: VersionDetail) => new Map(d.clips.map((c) => [c.id, c]));
  const issues = (d: VersionDetail) => {
    const m = new Map<number, Issue[]>();
    d.issues.forEach((i) => m.set(i.id, [...(m.get(i.id) ?? []), i]));
    return m;
  };
  const [ca, cb, ia, ib] = [byId(a), byId(b), issues(a), issues(b)];
  const tempo = (c: Clip | undefined) => (c && c.tempo > 1.0 ? c.tempo : null);
  const out: { id: number; start: number; a: SideDiff; b: SideDiff }[] = [];
  for (const [id, x] of ca) {
    const y = cb.get(id);
    const differentText = !!y && x.text !== y.text;
    if (!ia.has(id) && !ib.has(id) && !differentText) continue;
    out.push({
      id, start: x.start,
      a: { issues: ia.get(id) ?? [], tempo: tempo(x), text: differentText ? x.text : null },
      b: { issues: ib.get(id) ?? [], tempo: tempo(y), text: differentText ? y!.text : null },
    });
  }
  return out.sort((p, q) => p.id - q.id);
}
