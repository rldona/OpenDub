import type { Lang } from "./i18n";

/** 1:07 · 18:54 */
export function duration(s: number | null | undefined): string {
  if (s == null) return "";
  const t = Math.round(s);
  const h = Math.floor(t / 3600);
  const m = Math.floor((t % 3600) / 60);
  const sec = String(t % 60).padStart(2, "0");
  return h ? `${h}:${String(m).padStart(2, "0")}:${sec}` : `${m}:${sec}`;
}

/** 45 s · 12 min · 1 h 05 min */
export function clock(s: number): string {
  const t = Math.round(s);
  if (t < 60) return `${t} s`;
  const m = Math.floor(t / 60);
  if (m < 60) return `${m} min`;
  return `${Math.floor(m / 60)} h ${String(m % 60).padStart(2, "0")} min`;
}

/** Today: 11:34 · another day: Oct 24, 11:34 */
export function when(iso: string | null | undefined, lang: Lang): string {
  if (!iso) return "";
  const d = new Date(iso);
  const time = d.toLocaleTimeString(lang, { hour: "2-digit", minute: "2-digit" });
  if (d.toDateString() === new Date().toDateString()) return time;
  return `${d.toLocaleDateString(lang, { day: "numeric", month: "short" })}, ${time}`;
}

export function seconds(s: number, lang: Lang): string {
  return `${(Math.round(s * 10) / 10).toLocaleString(lang)} s`;
}

export function percent(x: number, lang: Lang): string {
  return `${(Math.round(x * 1000) / 10).toLocaleString(lang)}%`;
}
