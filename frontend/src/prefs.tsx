import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import type { EngineChoice } from "./api";
import { translate, type Key, type Lang } from "./i18n";

export type Theme = "system" | "dark" | "light";
export type Accent = "violet" | "coral" | "lime";

export interface Prefs {
  lang: Lang;
  theme: Theme;
  accent: Accent;
  tts: "clone" | "edge";
  engine: EngineChoice;
  separate: boolean;
  bgVolume: number;
  voice: string;
}

const KEY = "opendub.prefs";
const DEFAULTS: Prefs = {
  lang: "en", theme: "system", accent: "violet", tts: "clone", engine: "chatterbox", separate: true, bgVolume: 0,
  voice: "es-ES-AlvaroNeural",
};

// Spanish when the browser asks for any Spanish (es, es-ES, es-419…), English otherwise
export function browserLang(languages: readonly string[] = navigator.languages ?? [navigator.language]): Lang {
  const first = languages.find((l) => /^(es|en)\b/i.test(l)) ?? "";
  return first.toLowerCase().startsWith("es") ? "es" : "en";
}

// Browser storage can be missing or throw (private mode, blocked site data): never rely on it
function load(): Prefs {
  try {
    const saved = JSON.parse(localStorage.getItem(KEY) || "{}");
    const old = localStorage.getItem("ot.lang"); // the old page's setting
    const lang = saved.lang ?? (old === "es" || old === "en" ? old : browserLang());
    return { ...DEFAULTS, ...saved, lang };
  } catch {
    return { ...DEFAULTS, lang: browserLang() };
  }
}

interface PrefsContext {
  prefs: Prefs;
  set: (change: Partial<Prefs>) => void;
  t: (key: Key, vars?: Record<string, string | number>) => string;
}

const Context = createContext<PrefsContext | null>(null);

export function PrefsProvider({ children }: { children: ReactNode }) {
  const [prefs, setPrefs] = useState<Prefs>(load);
  const set = useCallback((change: Partial<Prefs>) => {
    setPrefs((old) => {
      const next = { ...old, ...change };
      try {
        localStorage.setItem(KEY, JSON.stringify(next));
      } catch {
        /* kept for this visit only */
      }
      return next;
    });
  }, []);
  useEffect(() => {
    const root = document.documentElement;
    root.lang = prefs.lang;
    root.dataset.accent = prefs.accent;
    if (prefs.theme === "system") delete root.dataset.theme;
    else root.dataset.theme = prefs.theme;
  }, [prefs.lang, prefs.accent, prefs.theme]);
  const value = useMemo<PrefsContext>(
    () => ({ prefs, set, t: (key, vars) => translate(prefs.lang, key, vars) }),
    [prefs, set],
  );
  return <Context.Provider value={value}>{children}</Context.Provider>;
}

export function usePrefs(): PrefsContext {
  const ctx = useContext(Context);
  if (!ctx) throw new Error("usePrefs outside PrefsProvider");
  return ctx;
}

/** The theme actually shown: the system's when the preference is "system". */
export function useResolvedTheme(): "dark" | "light" {
  const { prefs } = usePrefs();
  const query = "(prefers-color-scheme: dark)";
  const [systemDark, setSystemDark] = useState(() => window.matchMedia(query).matches);
  useEffect(() => {
    const mq = window.matchMedia(query);
    const on = () => setSystemDark(mq.matches);
    mq.addEventListener("change", on);
    return () => mq.removeEventListener("change", on);
  }, []);
  return prefs.theme === "system" ? (systemDark ? "dark" : "light") : prefs.theme;
}
