import { useState, type CSSProperties, type ReactNode } from "react";
import { media, type Status } from "./api";
import { engineShort } from "./catalog";
import { usePrefs } from "./prefs";

export function Logo({ size = 30 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 48 48" aria-hidden="true">
      <path d="M8 10h32a4 4 0 0 1 4 4v16a4 4 0 0 1-4 4H22l-9 7v-7H8a4 4 0 0 1-4-4V14a4 4 0 0 1 4-4z" fill="var(--accent)" />
      <path d="M14 20v4M19 16v12M24 18v8M29 14v16M34 20v4" stroke="var(--bg)" strokeWidth="2.6" strokeLinecap="round" />
    </svg>
  );
}

const ICONS: Record<string, ReactNode> = {
  library: (
    <>
      <rect x="3" y="3" width="7" height="7" rx="1" />
      <rect x="14" y="3" width="7" height="7" rx="1" />
      <rect x="3" y="14" width="7" height="7" rx="1" />
      <rect x="14" y="14" width="7" height="7" rx="1" />
    </>
  ),
  compare: (
    <>
      <rect x="3" y="4" width="8" height="16" rx="1" />
      <rect x="13" y="4" width="8" height="16" rx="1" />
    </>
  ),
  engines: <path d="M4 10v4M8 7v10M12 4v16M16 8v8M20 11v2" />,
  preferences: <path d="M4 21v-7M4 10V3M12 21v-9M12 8V3M20 21v-5M20 12V3M1 14h6M9 8h6M17 16h6" />,
  moon: <path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z" />,
  sun: (
    <>
      <circle cx="12" cy="12" r="4" />
      <path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" />
    </>
  ),
  close: <path d="M6 6l12 12M18 6L6 18" />,
};

export function Icon({ name, size = 18 }: { name: keyof typeof ICONS; size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
      strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      {ICONS[name]}
    </svg>
  );
}

export function PlayIcon({ size = 13 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
      <path d="M8 5v14l11-7z" />
    </svg>
  );
}

export function PauseIcon({ size = 13 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
      <path d="M7 5h4v14H7zM13 5h4v14h-4z" />
    </svg>
  );
}

/** An engine's colored dot and short name. */
export function EngineTag({ engine, extra }: { engine: string | null; extra?: string }) {
  return (
    <span className="tag">
      <span className={`dot ${engine ?? ""}`} />
      {engineShort(engine)}
      {extra}
    </span>
  );
}

export function StatusBadge({ status, label }: { status: Status; label?: string }) {
  const { t } = usePrefs();
  return <span className={`badge ${status}`}>{label ?? t(`status_${status}`)}</span>;
}

/** While a page's data is on its way: a spinner and the word, instead of a bare "…". */
export function Loading() {
  const { t } = usePrefs();
  return (
    <p className="muted loading" role="status">
      <span className="spinner" aria-hidden="true" />
      {t("loading")}
    </p>
  );
}

/** A video's thumbnail; until there is one (a dub still downloading), the grey box alone.
 *  `retry` changes (e.g. the job's phase) ask for it again. */
export function Thumb({ id, retry, style, lazy }: { id: string; retry?: string; style?: CSSProperties; lazy?: boolean }) {
  const [failed, setFailed] = useState<string | null>(null);
  const attempt = retry ?? "";
  if (failed === attempt) return <div className="thumb" style={style} aria-hidden="true" />;
  const src = media.thumbnail(id) + (attempt ? `?r=${encodeURIComponent(attempt)}` : "");
  return <img className="thumb" style={style} src={src} alt="" loading={lazy ? "lazy" : undefined} onError={() => setFailed(attempt)} />;
}
