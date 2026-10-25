import { useEffect, useRef } from "react";
import type { Register, Style, Variant } from "../api";
import { Icon } from "../components";
import { usePrefs } from "../prefs";

export const EMPTY_STYLE: Style = { register: "auto", variant: "auto", terms: [], notes: "" };

/** Without blank glossary rows, to compare and to save. */
export function cleanStyle(style: Style): Style {
  return {
    ...style,
    terms: style.terms.map((t) => ({ source: t.source.trim(), target: t.target.trim() })).filter((t) => t.source),
    notes: style.notes.trim(),
  };
}

export function sameStyle(a: Style, b: Style): boolean {
  return JSON.stringify(cleanStyle(a)) === JSON.stringify(cleanStyle(b));
}

/** Register, variant, glossary and notes. `inherited` (the global style, on a video) shows what "auto"
 * and an empty glossary fall back to; `used` marks the terms the video says. */
export function StyleEditor({ value, onChange, inherited, used, focusLast, idPrefix }: {
  value: Style;
  onChange: (style: Style) => void;
  inherited?: Style;
  used?: string[];
  focusLast?: number; // bumped to focus the last term's translation (after "Add to glossary")
  idPrefix: string;
}) {
  const { t } = usePrefs();
  const lastTarget = useRef<HTMLInputElement>(null);
  useEffect(() => {
    if (focusLast) lastTarget.current?.focus();
  }, [focusLast]);

  const registers: Register[] = ["auto", "tu", "usted"];
  const variants: Variant[] = ["auto", "es-ES", "latam"];
  const autoLabel = (key: "register" | "variant") => {
    const from = inherited?.[key];
    return from && from !== "auto" ? t("auto_from", { v: t(`${key}_${from}` as never) }) : t(`${key}_auto` as never);
  };
  const setTerm = (i: number, field: "source" | "target", text: string) =>
    onChange({ ...value, terms: value.terms.map((term, j) => (j === i ? { ...term, [field]: text } : term)) });
  const says = (source: string) => used?.some((u) => u.toLowerCase() === source.trim().toLowerCase());
  const shared = (inherited?.terms ?? []).filter(
    (g) => !value.terms.some((term) => term.source.trim().toLowerCase() === g.source.toLowerCase()));

  return (
    <div className="stack" style={{ gap: 16 }}>
      <div className="grid-2">
        <div className="field">
          <span id={`${idPrefix}-register`}>{t("register")}</span>
          <div className="segmented" role="radiogroup" aria-labelledby={`${idPrefix}-register`} style={{ width: "fit-content" }}>
            {registers.map((r) => (
              <button key={r} type="button" role="radio" aria-checked={value.register === r} onClick={() => onChange({ ...value, register: r })}>
                {r === "auto" ? autoLabel("register") : t(`register_${r}`)}
              </button>
            ))}
          </div>
        </div>
        <div className="field">
          <span id={`${idPrefix}-variant`}>{t("variant")}</span>
          <div className="segmented" role="radiogroup" aria-labelledby={`${idPrefix}-variant`} style={{ width: "fit-content" }}>
            {variants.map((v) => (
              <button key={v} type="button" role="radio" aria-checked={value.variant === v} onClick={() => onChange({ ...value, variant: v })}>
                {v === "auto" ? autoLabel("variant") : t(`variant_${v}`)}
              </button>
            ))}
          </div>
        </div>
      </div>

      <fieldset className="stack" style={{ margin: 0, padding: 0, border: 0, gap: 8 }}>
        <legend style={{ padding: 0, marginBottom: 4 }}>
          {t("glossary")} <span className="small faint">· {t("glossary_hint")}</span>
        </legend>
        {value.terms.map((term, i) => (
          <div key={i} className="row" style={{ gap: 8, flexWrap: "nowrap" }}>
            <input className="input" style={{ flex: 1 }} value={term.source} placeholder={t("term_source")}
              aria-label={t("term_source_n", { n: i + 1 })} onChange={(e) => setTerm(i, "source", e.target.value)} />
            <span className="faint" aria-hidden="true">→</span>
            <input className="input" style={{ flex: 1 }} value={term.target} placeholder={t("term_keep")}
              ref={i === value.terms.length - 1 ? lastTarget : undefined}
              aria-label={t("term_target_n", { n: i + 1 })} onChange={(e) => setTerm(i, "target", e.target.value)} />
            <span className="small" style={{ width: 92, color: says(term.source) ? "var(--accent-text)" : "var(--faint)" }}>
              {used && term.source.trim() ? (says(term.source) ? t("term_said") : t("term_unsaid")) : ""}
            </span>
            <button type="button" className="icon-btn" aria-label={t("term_remove_n", { n: i + 1 })}
              onClick={() => onChange({ ...value, terms: value.terms.filter((_, j) => j !== i) })}><Icon name="close" size={16} /></button>
          </div>
        ))}
        <div>
          <button type="button" className="btn" onClick={() => onChange({ ...value, terms: [...value.terms, { source: "", target: "" }] })}>
            {t("term_add")}
          </button>
        </div>
        {shared.length > 0 && (
          <p className="small muted" style={{ margin: 0 }}>
            {t("glossary_shared")}{" "}
            {shared.map((g) => `${g.source} → ${g.target || g.source}`).join(" · ")}
          </p>
        )}
      </fieldset>

      <label className="field">
        {t("style_notes")}
        <textarea className="input" rows={2} value={value.notes} placeholder={t("style_notes_hint")}
          onChange={(e) => onChange({ ...value, notes: e.target.value })} />
      </label>
    </div>
  );
}
