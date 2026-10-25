import { useEffect, useState, type ReactNode } from "react";
import { api, type EngineStatus, type ServerStatus } from "./api";
import { Icon, Logo } from "./components";
import { overall, useJobs } from "./job";
import { Compare } from "./pages/Compare";
import { Engines } from "./pages/Engines";
import { Library } from "./pages/Library";
import { Preferences } from "./pages/Preferences";
import { VideoPage } from "./pages/Video";
import { usePrefs, useResolvedTheme } from "./prefs";

/** Hash routes: #/ · #/video/<id> · #/compare/<id> · #/engines · #/preferences */
export type Route =
  | { page: "library" }
  | { page: "video"; id: string }
  | { page: "compare"; id: string | null }
  | { page: "engines" }
  | { page: "preferences" };

function parse(hash: string): Route {
  const [, page, id] = hash.replace(/^#\/?/, "/").split("/");
  if (page === "video" && id) return { page: "video", id };
  if (page === "compare") return { page: "compare", id: id || null };
  if (page === "engines") return { page: "engines" };
  if (page === "preferences") return { page: "preferences" };
  return { page: "library" };
}

function useRoute(): Route {
  const [route, setRoute] = useState(() => parse(location.hash));
  useEffect(() => {
    const on = () => {
      setRoute(parse(location.hash));
      window.scrollTo(0, 0);
    };
    window.addEventListener("hashchange", on);
    return () => window.removeEventListener("hashchange", on);
  }, []);
  return route;
}

/** The engines' install status, loaded once per page. */
export function useEngines(): EngineStatus[] | null {
  const [engines, setEngines] = useState<EngineStatus[] | null>(null);
  useEffect(() => {
    api.engines().then(setEngines).catch(() => setEngines(null));
  }, []);
  return engines;
}

export function App() {
  const route = useRoute();
  const { t } = usePrefs();
  const section = route.page === "video" ? "library" : route.page;
  return (
    <div className="app">
      <TopBar />
      <div className="body">
        <nav className="sidebar" aria-label={t("main_nav")}>
          <span className="section">{t("workspace")}</span>
          <NavLink to="#/" icon="library" current={section === "library"}>{t("library")}</NavLink>
          <NavLink to="#/compare" icon="compare" current={section === "compare"}>{t("compare")}</NavLink>
          <span className="section">{t("setup")}</span>
          <NavLink to="#/engines" icon="engines" current={section === "engines"}>{t("engines")}</NavLink>
          <NavLink to="#/preferences" icon="preferences" current={section === "preferences"}>{t("preferences")}</NavLink>
        </nav>
        <main className="content">
          {route.page === "library" && <Library />}
          {route.page === "video" && <VideoPage key={route.id} id={route.id} />}
          {route.page === "compare" && <Compare id={route.id} />}
          {route.page === "engines" && <Engines />}
          {route.page === "preferences" && <Preferences />}
        </main>
      </div>
      <Footer />
    </div>
  );
}

function NavLink({ to, icon, current, children }: { to: string; icon: "library" | "compare" | "engines" | "preferences"; current: boolean; children: ReactNode }) {
  return (
    <a className="nav-link" href={to} aria-current={current ? "page" : undefined}>
      <Icon name={icon} />
      {children}
    </a>
  );
}

function TopBar() {
  const { prefs, set, t } = usePrefs();
  const theme = useResolvedTheme();
  const { job, queued } = useJobs();
  const running = job && (job.status === "running" || job.status === "queued");
  return (
    <header className="topbar">
      <a className="brand" href="#/">
        <Logo />
        <span>Open<strong>Dub</strong></span>
      </a>
      <div className="topbar-actions">
        {running && (
          <a className="job-pill" href={`#/video/${job.id}`}>
            <span className="dot accent" />
            <span className="label">{t("dubbing_pct", { p: Math.floor(overall(job) * 100) })}</span>
            {queued.length > 0 && <span className="label">· {t("queued_pill", { n: queued.length })}</span>}
          </a>
        )}
        <button type="button" className="icon-btn" onClick={() => set({ theme: theme === "dark" ? "light" : "dark" })}
          aria-label={theme === "dark" ? t("theme_to_light") : t("theme_to_dark")}>
          <Icon name={theme === "dark" ? "sun" : "moon"} />
        </button>
        <label>
          <span className="sr-only">{t("language")}</span>
          <select className="plain-select" value={prefs.lang} onChange={(e) => set({ lang: e.target.value as "en" | "es" })}>
            <option value="en">English</option>
            <option value="es">Español</option>
          </select>
        </label>
      </div>
    </header>
  );
}

function Footer() {
  const { t } = usePrefs();
  const { finished } = useJobs();
  const [status, setStatus] = useState<ServerStatus | null | undefined>(undefined);
  useEffect(() => {
    let alive = true;
    const load = () => api.status().then((s) => alive && setStatus(s)).catch(() => alive && setStatus(null));
    load();
    const timer = window.setInterval(load, 10000);
    return () => {
      alive = false;
      window.clearInterval(timer);
    };
  }, [finished]);
  return (
    <footer className="footer">
      <span>
        <span className={`dot ${status === null ? "bad" : "ok"}`} />
        {status === null ? t("unreachable") : status ? t("connected", { r: status.running, q: status.queued }) : ""}
      </span>
      {status && <span className="mono">opendub {status.version} · {status.work_root}/</span>}
    </footer>
  );
}
