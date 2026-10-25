"use strict";

// ---- i18n ------------------------------------------------------------------
const STRINGS = {
  en: {
    preferences: "Preferences", language: "Language", dub: "Dub", voice: "Voice", voice_clone: "Cloned",
    voice_edge: "edge-tts", engine: "Engine", engine_auto: "Automatic", keep_music: "Keep the music",
    bg_volume: "Background volume", videos: "Videos",
    videos_empty: "Paste a YouTube link above to dub your first video.",
    url_required: "Paste a YouTube link or video id.", queued: "queued", running: "in progress", done: "Done",
    error: "Error", pending: "Not dubbed", in_queue: "{n} in queue", status_queued: "Queued",
    status_running: "In progress", status_done: "Done", status_error: "Failed",
    Download: "Download", Transcription: "Transcription", Separation: "Separation",
    Translation: "Translation", TTS: "Voice", Mix: "Mix", play: "Play", hide: "Hide", download_file: "Download",
    details: "Details", retry: "Retry", back: "Videos", failed_in: "Failed: {msg}", issues_n: "{n} issues",
    regenerate: "Regenerate voice and mix", save: "Save translation", discard: "Discard changes",
    saved: "Saved. Regenerate the voice and mix to hear it.", unsaved: "{n} unsaved changes",
    needs_regen: "The translation changed since the last mix.", translation: "Translation",
    original: "Original", spanish: "Spanish", fit: "Slot · chars", issues: "Clips with problems",
    no_issues: "No clips with problems.", edit_segment: "Edit segment {n}", listen: "Listen to clip {n}",
    kind_overflow: "Doesn't fit", kind_fallback: "edge-tts", kind_floor: "Below floor",
    kind_abnormal: "Abnormal", kind_delayed: "Delayed", kind_repaired: "Redone",
    clips: "{n} segments", sped_up: "{n} sped up", shortened: "{n} shortened", ref_f0: "Reference F0 {f0} Hz",
    engine_label: "Engine {e}", not_found: "This video isn't in the work folder.", start_dub: "Dub",
    cant_reach: "Can't reach the server. Is `opentranslator web` running?",
    overall: "Overall {p}%", eta_min: "about {m} min left", eta_sec: "under a minute left",
    elapsed: "{t} elapsed", took: "took {t}", estimating: "estimating time left…",
    finishing: "finishing: fitting and quality check…",
    version: "Version", latest: "latest", edited: "edited by hand",
    engine_note_auto: "Chatterbox or IndexTTS by the voice's pitch",
    engine_note_chatterbox: "MIT · preferred by ear for female voices",
    engine_note_indextts: "bilibili license · preferred by ear for male voices",
    engine_note_cosyvoice: "Apache 2.0 · fits almost every slot as is",
    not_installed: "not installed", install_hint: "{e} is not installed: {cmd}",
    regen_engine: "Regenerate with another engine",
    regen_engine_hint: "Keeps this translation: only the voice and the mix are redone.",
  },
  es: {
    preferences: "Preferencias", language: "Idioma", dub: "Doblar", voice: "Voz", voice_clone: "Clonada",
    voice_edge: "edge-tts", engine: "Motor", engine_auto: "Automático", keep_music: "Conservar la música",
    bg_volume: "Volumen de fondo", videos: "Vídeos",
    videos_empty: "Pega arriba un enlace de YouTube para doblar tu primer vídeo.",
    url_required: "Pega un enlace de YouTube o el id del vídeo.", queued: "en cola", running: "en curso",
    done: "Hecho", error: "Error", pending: "Sin doblar", in_queue: "{n} en cola", status_queued: "En cola",
    status_running: "En curso", status_done: "Hecho", status_error: "Falló",
    Download: "Descarga", Transcription: "Transcripción", Separation: "Separación",
    Translation: "Traducción", TTS: "Voz", Mix: "Mezcla", play: "Reproducir", hide: "Ocultar",
    download_file: "Descargar", details: "Detalle", retry: "Reintentar", back: "Vídeos",
    failed_in: "Falló: {msg}", issues_n: "{n} avisos", regenerate: "Regenerar voz y mezcla",
    save: "Guardar traducción", discard: "Descartar cambios",
    saved: "Guardado. Regenera la voz y la mezcla para oírlo.", unsaved: "{n} cambios sin guardar",
    needs_regen: "La traducción ha cambiado desde la última mezcla.", translation: "Traducción",
    original: "Original", spanish: "Español", fit: "Hueco · car.", issues: "Clips con problema",
    no_issues: "Ningún clip con problema.", edit_segment: "Editar el segmento {n}", listen: "Escuchar el clip {n}",
    kind_overflow: "No cabe", kind_fallback: "edge-tts", kind_floor: "Bajo el suelo",
    kind_abnormal: "Anómalo", kind_delayed: "Retrasado", kind_repaired: "Rehecho",
    clips: "{n} segmentos", sped_up: "{n} acelerados", shortened: "{n} acortados", ref_f0: "F0 de la referencia {f0} Hz",
    engine_label: "Motor {e}", not_found: "Este vídeo no está en la carpeta de trabajo.", start_dub: "Doblar",
    cant_reach: "No hay conexión con el servidor. ¿Está corriendo `opentranslator web`?",
    overall: "Total {p} %", eta_min: "faltan unos {m} min", eta_sec: "falta menos de un minuto",
    elapsed: "lleva {t}", took: "tardó {t}", estimating: "calculando lo que falta…",
    finishing: "terminando: ajuste y control de calidad…",
    version: "Versión", latest: "la última", edited: "editada a mano",
    engine_note_auto: "Chatterbox o IndexTTS según el tono de la voz",
    engine_note_chatterbox: "MIT · la preferida de oído en voces femeninas",
    engine_note_indextts: "licencia bilibili · la preferida de oído en voces masculinas",
    engine_note_cosyvoice: "Apache 2.0 · cabe casi todo sin ajustar",
    not_installed: "sin instalar", install_hint: "{e} no está instalado: {cmd}",
    regen_engine: "Regenerar con otro motor",
    regen_engine_hint: "Conserva esta traducción: solo se rehacen la voz y la mezcla.",
  },
};

function storageGet(key) { try { return localStorage.getItem(key); } catch { return null; } }
function storageSet(key, value) { try { localStorage.setItem(key, value); } catch { /* private mode */ } }

let lang = storageGet("ot.lang") === "es" ? "es" : "en";
function t(key, vars = {}) {
  const s = (STRINGS[lang] && STRINGS[lang][key]) ?? STRINGS.en[key] ?? key;
  return s.replace(/\{(\w+)\}/g, (_, k) => vars[k] ?? "");
}
function applyI18n() {
  document.documentElement.lang = lang;
  document.querySelectorAll("[data-i18n]").forEach((el) => { el.textContent = t(el.dataset.i18n); });
}

// ---- helpers ---------------------------------------------------------------
const $ = (sel, root = document) => root.querySelector(sel);
function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v === null || v === undefined || v === false) continue;
    if (k === "class") node.className = v;
    else if (k.startsWith("on")) node.addEventListener(k.slice(2), v);
    else if (v === true) node.setAttribute(k, "");
    else node.setAttribute(k, v);
  }
  for (const c of children.flat()) if (c !== null && c !== undefined) node.append(c);
  return node;
}
async function api(path, opts = {}) {
  let r;
  try {
    r = await fetch(path, { headers: { "Content-Type": "application/json" }, ...opts });
  } catch {
    throw new Error(t("cant_reach"));
  }
  if (!r.ok) {
    let msg = r.statusText;
    try { const body = await r.json(); msg = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail); } catch { /* not json */ }
    throw new Error(msg);
  }
  return r.json();
}
function duration(s) {
  if (s == null) return "";
  s = Math.round(s);
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}
function clock(s) {
  // 45 s · 12 min · 1 h 05 min
  s = Math.round(s);
  if (s < 60) return `${s} s`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m} min`;
  return `${Math.floor(m / 60)} h ${String(m % 60).padStart(2, "0")} min`;
}
function seconds(s) { return `${(Math.round(s * 10) / 10).toLocaleString(lang)} s`; }
function when(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  return d.toLocaleString(lang, { dateStyle: "medium", timeStyle: "short" });
}

// ---- preferences -----------------------------------------------------------
function initPrefs() {
  const toggle = $("#prefs-toggle"), panel = $("#prefs"), select = $("#lang");
  select.value = lang;
  toggle.addEventListener("click", () => {
    panel.hidden = !panel.hidden;
    toggle.setAttribute("aria-expanded", String(!panel.hidden));
  });
  select.addEventListener("change", () => {
    lang = select.value;
    storageSet("ot.lang", lang);
    applyI18n();
    renderEngines();
    renderJob();
    loadVideos();
    if (location.hash.startsWith("#/video/")) route();
  });
}

// ---- cloning engines ---------------------------------------------------------
let engineList = [{ id: "auto", name: "Automatic", installed: true }]; // GET /engines replaces it

function engineName(e) { return e.id === "auto" ? t("engine_auto") : e.name; }

function fillEngines(select, selected) {
  // name — license and what it stands out for (docs/v2-plan.md); engines without their venv can't be picked
  const value = selected ?? select.value;
  select.replaceChildren(...engineList.map((e) => el("option", {
    value: e.id, disabled: !e.installed, title: e.installed ? null : e.setup,
  }, `${engineName(e)} — ${t(`engine_note_${e.id}`)}${e.installed ? "" : ` (${t("not_installed")})`}`)));
  const usable = engineList.find((e) => e.id === value && e.installed) || engineList.find((e) => e.installed);
  if (usable) select.value = usable.id;
}

function installHints() {
  return engineList.filter((e) => !e.installed && e.id !== "auto")
    .map((e) => t("install_hint", { e: e.name, cmd: e.setup })).join(" · ");
}

function renderEngines() {
  fillEngines($("#engine"));
  const hint = $("#engine-hint");
  hint.textContent = installHints();
  hint.hidden = !hint.textContent;
}

async function loadEngines() {
  try { engineList = await api("/engines"); } catch { /* keep the fallback */ }
  renderEngines();
  if (detail) renderDetail();
}

// ---- dub form --------------------------------------------------------------
function formOptions() {
  return {
    url: $("#url").value.trim(),
    tts: $("#tts").value,
    engine: $("#engine").value,
    separate: $("#separate").checked,
    bg_volume: Number($("#bg-volume").value),
  };
}
function initForm() {
  const form = $("#dub-form"), url = $("#url"), error = $("#form-error");
  const volume = $("#bg-volume"), out = $("#bg-volume-out"), separate = $("#separate"), tts = $("#tts");
  let volumeTouched = false;
  const showVolume = () => { out.textContent = `${volume.value} dB`; };
  volume.addEventListener("input", () => { volumeTouched = true; showVolume(); });
  separate.addEventListener("change", () => {
    if (!volumeTouched) { volume.value = separate.checked ? 0 : -15; showVolume(); }
  });
  tts.addEventListener("change", () => { $("#engine").closest("label").hidden = tts.value !== "clone"; });
  url.addEventListener("input", () => { error.hidden = true; });
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const opts = formOptions();
    if (!opts.url) { error.textContent = t("url_required"); error.hidden = false; url.focus(); return; }
    try {
      const job = await api("/jobs", { method: "POST", body: JSON.stringify(opts) });
      url.value = "";
      watch(job.id);
      loadVideos();
    } catch (err) {
      error.textContent = err.message; error.hidden = false;
    }
  });
  showVolume();
}

// ---- running job (SSE) -----------------------------------------------------
const PHASES = ["Download", "Transcription", "Separation", "Translation", "TTS", "Mix"];
// Share of a dub's time per phase, measured on a 28-minute video with a cloned voice
const PHASE_WEIGHTS = { Download: 1, Transcription: 1, Separation: 2, Translation: 9, TTS: 86, Mix: 1 };
let source = null;
let job = null; // {id, title, status, error, phases: {name: {state, seconds}}, progress, logs, queue}

function newJob(id) {
  return { id, title: id, status: "queued", error: null, phases: {}, progress: null, logs: [], queue: 0,
           active: null, phaseFrac: {}, startedAt: null, segments: null, clipsDone: 0, lastCompleted: 0,
           firstPassAt: null, laterBatches: 0 };
}

function watch(id) {
  if (source) source.close();
  job = newJob(id);
  renderJob();
  const known = videos.find((v) => v.id === id);
  if (known) { job.title = known.title; renderJob(); }
  source = new EventSource(`/jobs/${id}/events`);
  source.onmessage = (msg) => { handleEvent(JSON.parse(msg.data)); };
  source.addEventListener("end", () => { source.close(); source = null; finishJob(); });
}

function handleEvent(e) {
  if (!job) return;
  if (e.type === "status") {
    job.status = e.status;
    if (e.error) job.error = e.error;
    if (e.status === "running") job.startedAt = e.t;
    if (e.status === "done" || e.status === "error") job.finishedAt = e.t;
  } else if (e.type === "phase") {
    job.phases[e.name] = { state: e.state === "start" ? "active" : e.state, seconds: e.seconds };
    if (e.state === "start") {
      job.active = e.name;
      job.progress = null;
      // a phase that started after Separation's slot without it means Separation was skipped
      const at = PHASES.indexOf(e.name);
      PHASES.slice(0, at).forEach((p) => { if (!job.phases[p]) job.phases[p] = { state: "skipped" }; });
    }
  } else if (e.type === "progress") {
    job.progress = e;
    // the overall bar never goes back: later, smaller bars (quality check, shortening) don't reset it
    if (job.active === "TTS" && job.segments) {
      // The first pass speaks every segment (maybe over several bars: count clips across them) and is
      // 60% of the phase. What follows (fitting, quality check, shortening) has no known total, and took
      // about as long on a long video: each later batch moves the bar a bit, never to the end.
      if (e.completed < job.lastCompleted) {
        if (job.firstPassAt) job.laterBatches += 1;
        job.clipsDone += job.lastCompleted;
      }
      job.lastCompleted = e.completed;
      const first = Math.min(1, (job.clipsDone + e.completed) / job.segments);
      if (first >= 1 && !job.firstPassAt) job.firstPassAt = e.t;
      const later = job.firstPassAt ? 1 - 0.6 ** job.laterBatches : 0;
      job.phaseFrac.TTS = Math.max(job.phaseFrac.TTS || 0, 0.6 * first + 0.4 * later * 0.9);
    } else if (job.active && e.total) {
      job.phaseFrac[job.active] = Math.max(job.phaseFrac[job.active] || 0, Math.min(1, e.completed / e.total));
    }
  } else if (e.type === "log") {
    job.logs.push(e);
    if (job.logs.length > 4) job.logs.shift();
    const m = /^\s*(.+?) · \d+s · language/.exec(e.message);
    if (m) job.title = m[1];
    const n = /· (\d+) segments$/.exec(e.message);  // "Cloned voice: … · 353 segments"
    if (n && job.active === "TTS") job.segments = Number(n[1]);
  }
  scheduleRender();
}

let renderPending = false;
function scheduleRender() {
  if (renderPending) return;
  renderPending = true;
  requestAnimationFrame(() => { renderPending = false; renderJob(); });
}

function overallFraction() {
  let done = 0, total = 0;
  for (const p of PHASES) {
    const w = PHASE_WEIGHTS[p];
    const state = (job.phases[p] || {}).state;
    total += w;
    if (state === "done" || state === "skipped") done += w;
    else if (state === "active") done += w * (job.phaseFrac[p] || 0);
  }
  return job.status === "done" ? 1 : done / total;
}

function renderOverall() {
  const f = overallFraction();
  const pct = Math.floor(f * 100);
  $("#overall-label").textContent = t("overall", { p: pct });
  $("#overall-fill").style.width = `${(f * 100).toFixed(1)}%`;
  $("#overall-meter").setAttribute("aria-valuenow", String(pct));
  const parts = [];
  if (job.startedAt && (job.status === "running" || job.finishedAt)) {
    const end = job.status === "running" ? Date.now() / 1000 : job.finishedAt;
    const elapsed = Math.max(0, end - job.startedAt);
    if (job.status === "running") {
      parts.push(t("elapsed", { t: clock(elapsed) }));
      if (job.active === "TTS" && job.firstPassAt) {
        parts.push(t("finishing"));  // no honest estimate for what's left of the phase
      } else if (f >= 0.05 && elapsed >= 20) {  // enough of the job behind to extrapolate from
        const left = (elapsed * (1 - f)) / f;
        parts.push(left < 60 ? t("eta_sec") : t("eta_min", { m: Math.round(left / 60) }));
      } else {
        parts.push(t("estimating"));
      }
    } else {
      parts.push(t("took", { t: clock(elapsed) }));
    }
  }
  $("#overall-eta").textContent = parts.join(" · ");
}

function renderJob() {
  const card = $("#job");
  if (!job) { card.hidden = true; return; }
  card.hidden = false;
  $("#job-title").textContent = job.title;
  const state = job.status === "error" ? t("failed_in", { msg: job.error || "" }) : t(job.status);
  $("#job-state").textContent = job.queue ? `${state} · ${t("in_queue", { n: job.queue })}` : state;
  $("#job-state").className = job.status === "error" ? "error" : "muted";
  $("#phases").replaceChildren(...PHASES.map((p) => {
    const ph = job.phases[p] || { state: "pending" };
    let detail = "—";
    if (ph.state === "done" && ph.seconds != null) detail = seconds(ph.seconds);
    if (ph.state === "active" && job.progress && job.progress.total) {
      detail = `${Math.round(job.progress.completed)} / ${Math.round(job.progress.total)}`;
    }
    if (ph.state === "active" && !(job.progress && job.progress.total)) detail = "…";
    return el("li", { class: ph.state, "aria-current": ph.state === "active" ? "step" : null },
      t(p), el("small", {}, detail));
  }));
  const meter = $("#meter"), fill = $("#meter-fill"), label = $("#progress-label");
  const running = job.status === "running";
  const p = job.progress;
  meter.hidden = !running;
  label.textContent = running && p ? `${p.task}${p.total ? ` · ${Math.round(p.completed)} / ${Math.round(p.total)}` : ""}` : "";
  if (running && p && p.total) {
    meter.classList.remove("indeterminate");
    fill.style.width = `${Math.min(100, (100 * p.completed) / p.total).toFixed(1)}%`;
  } else {
    meter.classList.toggle("indeterminate", running);
    fill.style.width = running ? "" : "0";
  }
  renderOverall();
  $("#log").replaceChildren(...job.logs.slice().reverse().map((l) => el("li", { class: l.level }, l.message)));
}

async function finishJob() {
  await loadVideos();
  const active = await api("/jobs").catch(() => []);
  if (active.length) watch(active[0].id);
  else renderJob();
}

async function reconnect() {
  const active = await api("/jobs").catch(() => []);
  if (active.length) {
    watch(active[0].id);
    job.queue = active.length - 1;
  }
}

// ---- video list --------------------------------------------------------------
let videos = [];
let openPlayer = null;

async function loadVideos() {
  try {
    videos = await api("/videos");
  } catch {
    return;
  }
  if (job) {
    const v = videos.find((x) => x.id === job.id);
    if (v && v.title) job.title = v.title;
    job.queue = videos.filter((x) => x.status === "queued").length - (job.status === "queued" ? 1 : 0);
    if (job.queue < 0) job.queue = 0;
    renderJob();
  }
  renderVideos();
}

function statusBadge(status) {
  return el("span", { class: `badge ${status}` }, t(`status_${status}`) === `status_${status}` ? t("pending") : t(`status_${status}`));
}

let renderedList = "";

function renderVideos(force = false) {
  // The list refreshes every few seconds: repaint only when something shown changed,
  // and keep the open player element, so a playing video isn't cut
  const signature = JSON.stringify([lang, openPlayer, videos]);
  if (!force && signature === renderedList) return;
  renderedList = signature;
  const list = $("#videos");
  const player = openPlayer ? list.querySelector(`video[data-id="${openPlayer}"]`) : null;
  $("#videos-empty").hidden = videos.length > 0;
  list.replaceChildren(...videos.map((v) => {
    const meta = [duration(v.duration), when(v.date)];
    if (v.engine) meta.push(v.engine);
    if (v.issues) meta.push(t("issues_n", { n: v.issues }));
    const actions = [];
    if (v.status === "done") {
      actions.push(el("button", { type: "button", class: "icon", "aria-label": t("play"),
        onclick: () => togglePlayer(v.id) }, openPlayer === v.id ? t("hide") : t("play")));
      actions.push(el("a", { class: "badge", href: `/videos/${v.id}/output.mp4`, download: `${v.id}.es.mp4` }, t("download_file")));
    }
    if (v.status === "error" || v.status === "pending") {
      actions.push(el("button", { type: "button", onclick: () => redub(v.id) }, v.status === "error" ? t("retry") : t("start_dub")));
    }
    actions.push(el("a", { href: `#/video/${v.id}`, class: "badge" }, t("details")));
    const row = el("div", { class: "video-row" },
      el("img", { class: "thumb", src: `/videos/${v.id}/thumbnail`, alt: "", loading: "lazy" }),
      el("div", { class: "video-info" },
        el("div", { class: "title", title: v.title }, v.title || v.id),
        v.status === "error"
          ? el("div", { class: "meta error" }, t("failed_in", { msg: v.error || "" }))
          : el("div", { class: "meta" }, meta.filter(Boolean).join(" · "))),
      statusBadge(v.status),
      el("div", { class: "actions" }, actions));
    const item = el("li", { class: "video" }, row);
    if (openPlayer === v.id) {
      item.append(player || el("video", { controls: true, preload: "metadata", "data-id": v.id,
        src: `/videos/${v.id}/output.mp4` }));
    }
    return item;
  }));
}

function togglePlayer(id) {
  openPlayer = openPlayer === id ? null : id;
  renderVideos();
}

async function redub(id, overrides = {}) {
  const saved = await api(`/jobs/${id}`).catch(() => null);
  const base = saved && saved.options ? saved.options : formOptions();
  const opts = { ...base, ...overrides, url: id };
  const started = await api("/jobs", { method: "POST", body: JSON.stringify(opts) });
  location.hash = "#/";
  watch(started.id);
  loadVideos();
}

// ---- detail view -------------------------------------------------------------
let detail = null; // {id, video, segments, edits: Map(id → text)}

async function showDetail(id) {
  const section = $("#detail");
  $("#home").hidden = true;
  section.hidden = false;
  section.replaceChildren(el("p", { class: "muted" }, "…"));
  let video, translation, issues;
  try {
    [video, translation, issues] = await Promise.all([
      api(`/videos/${id}`), api(`/videos/${id}/translation`).catch(() => null), api(`/videos/${id}/issues`).catch(() => []),
    ]);
  } catch {
    section.replaceChildren(el("a", { href: "#/" }, `← ${t("back")}`), el("p", {}, t("not_found")));
    return;
  }
  detail = { id, video, translation, issues, edits: new Map(), savedNote: false, version: null };
  renderDetail();
}

function renderDetail() {
  const { id, video, translation, issues } = detail;
  const section = $("#detail");
  const info = [duration(video.duration)];
  if (video.engine) info.push(t("engine_label", { e: video.engine }));
  if (video.reference_f0_hz) info.push(t("ref_f0", { f0: Math.round(video.reference_f0_hz) }));
  if (video.clips) info.push(t("clips", { n: video.clips }), t("sped_up", { n: video.sped_up }), t("shortened", { n: video.shortened }));
  // one dub per engine is kept (outputs/<engine>.mp4): pick which one to watch
  const versions = video.outputs || [];
  const version = detail.version && versions.some((o) => o.engine === detail.version) ? detail.version : null;
  const src = version ? `/videos/${id}/outputs/${version}.mp4` : `/videos/${id}/output.mp4`;
  const picker = versions.length > 1
    ? el("div", { class: "versions", role: "group", "aria-label": t("version") },
        el("span", { class: "muted small" }, t("version")),
        versions.map((o) => {
          const active = version ? o.engine === version : o.current;
          return el("button", { type: "button", class: active ? "primary" : "", "aria-pressed": String(active),
            onclick: () => { detail.version = o.current ? null : o.engine; renderDetail(); } },
            o.engine + (o.current ? ` (${t("latest")})` : ""));
        }))
    : null;
  const head = el("div", { class: "detail-head" },
    video.status === "done"
      ? el("div", {}, el("video", { controls: true, preload: "metadata", src }), picker)
      : el("img", { class: "thumb", style: "width:100%", src: `/videos/${id}/thumbnail`, alt: "" }),
    el("div", {},
      el("h2", {}, video.title || id),
      el("div", { class: "muted small" }, info.filter(Boolean).join(" · ")),
      el("div", {}, statusBadge(video.status)),
      el("div", { class: "detail-actions" },
        video.status === "done" ? el("a", { class: "badge", href: src, download: `${id}.es${version ? "." + version : ""}.mp4` }, t("download_file")) : null,
        translation ? el("button", { type: "button", class: "primary", onclick: regenerate }, t("regenerate")) : null),
      translation ? otherEngine(video) : null,
      translation && translation.needs_regeneration && !detail.edits.size
        ? el("p", { class: "small", style: "color: var(--warning)" }, t("needs_regen")) : null));

  const parts = [el("a", { href: "#/" }, `← ${t("back")}`), head];
  if (translation) {
    parts.push(el("h2", {}, t("translation")));
    parts.push(el("table", { class: "segments" },
      el("thead", {}, el("tr", {}, el("th", {}, "#"), el("th", {}, t("original")), el("th", {}, t("spanish")), el("th", { style: "text-align:right" }, t("fit")))),
      el("tbody", {}, translation.segments.map(segmentRow))));
    const note = el("span", { class: "muted small", id: "save-note" });
    parts.push(el("div", { class: "save-bar" }, note,
      el("button", { type: "button", onclick: discardEdits }, t("discard")),
      el("button", { type: "button", onclick: saveEdits }, t("save"))));
  }
  parts.push(el("h2", {}, t("issues")));
  parts.push(issues.length
    ? el("ul", { class: "issues" }, issues.map((i) => el("li", {},
        el("span", { class: `badge ${i.kind === "fallback" ? "error" : "warning"}` }, t(`kind_${i.kind}`)),
        el("div", { class: "text" }, `#${i.id} · ${duration(i.start)} · ${i.message}`, el("span", { class: "muted" }, i.text ? ` · ${i.text}` : "")),
        i.wav ? el("audio", { controls: true, preload: "none", src: i.wav, "aria-label": t("listen", { n: i.id }) }) : null,
        translation ? el("button", { type: "button", class: "icon", "aria-label": t("edit_segment", { n: i.id }), onclick: () => focusSegment(i.id) }, "✎") : null)))
    : el("p", { class: "muted" }, t("no_issues")));
  section.replaceChildren(...parts);
  updateSaveNote();
}

function segmentRow(s) {
  const text = detail.edits.has(s.id) ? detail.edits.get(s.id) : s.text;
  const fit = el("td", { class: "fit" });
  const row = el("tr", { id: `seg-${s.id}` },
    el("td", { class: "muted small" }, String(s.id), el("br"), duration(s.start),
      s.edited ? el("span", { class: "edited", title: t("edited"), "aria-label": t("edited") }, " ✎") : null),
    el("td", { class: "original" }, s.original),
    el("td", { class: "es" }, el("textarea", { rows: 2, "aria-label": `${t("spanish")} #${s.id}`,
      oninput: (e) => { onEdit(s, e.target.value, row, fit); } }, text)),
    fit);
  paintFit(s, text, row, fit);
  return row;
}

function paintFit(s, text, row, fit) {
  const chars = [...text].length;
  fit.replaceChildren(seconds(s.slot), el("br"), s.max_chars ? `${chars} / ${s.max_chars}` : String(chars));
  row.classList.toggle("over", Boolean(s.max_chars) && chars > s.max_chars * 1.25);
}

function onEdit(s, value, row, fit) {
  if (value === s.text) detail.edits.delete(s.id); else detail.edits.set(s.id, value);
  paintFit(s, value, row, fit);
  detail.savedNote = false;
  updateSaveNote();
}

function updateSaveNote() {
  const note = $("#save-note");
  if (!note) return;
  if (detail.edits.size) note.textContent = t("unsaved", { n: detail.edits.size });
  else note.textContent = detail.savedNote ? t("saved") : "";
}

function discardEdits() {
  detail.edits.clear();
  detail.savedNote = false;
  renderDetail();
}

async function saveEdits() {
  if (!detail.edits.size) return;
  const body = [...detail.edits].map(([id, text]) => ({ id, text }));
  try {
    detail.translation = await api(`/videos/${detail.id}/translation`, { method: "PUT", body: JSON.stringify(body) });
    detail.edits.clear();
    detail.savedNote = true;
    renderDetail();
  } catch (err) {
    $("#save-note").textContent = err.message;
  }
}

function otherEngine(video) {
  // same video, same translation, another engine: only TTS and the mix run (outputs/<engine>.mp4 keeps each)
  const select = el("select", { "aria-label": t("engine") });
  const current = engineList.find((e) => e.id !== "auto" && e.id !== video.engine && e.installed);
  fillEngines(select, current ? current.id : undefined);
  const go = async () => {
    if (detail.edits.size) await saveEdits();
    if (detail.edits.size) return; // save failed
    await redub(detail.id, { tts: "clone", engine: select.value, keep_translation: true });
  };
  return el("div", { class: "other-engine" },
    el("div", { class: "row" }, select, el("button", { type: "button", onclick: go }, t("regen_engine"))),
    el("p", { class: "muted small" }, t("regen_engine_hint")));
}

async function regenerate() {
  if (detail.edits.size) await saveEdits();
  if (detail.edits.size) return; // save failed
  await redub(detail.id);
}

function focusSegment(id) {
  const row = document.getElementById(`seg-${id}`);
  if (!row) return;
  row.scrollIntoView({ behavior: "smooth", block: "center" });
  row.classList.remove("flash"); void row.offsetWidth; row.classList.add("flash");
  $("textarea", row).focus({ preventScroll: true });
}

// ---- routing ---------------------------------------------------------------
function route() {
  const m = /^#\/video\/([\w-]{11})$/.exec(location.hash);
  if (m) { showDetail(m[1]); return; }
  detail = null;
  $("#detail").hidden = true;
  $("#home").hidden = false;
  loadVideos();
}

window.addEventListener("hashchange", route);
applyI18n();
initPrefs();
initForm();
loadEngines();
route();
reconnect();
setInterval(() => { if (!document.hidden && !$("#home").hidden) loadVideos(); }, 15000);
setInterval(() => { if (job && job.status === "running" && !document.hidden) renderOverall(); }, 5000);
