// What the page says when a request fails: the server's error code in the page's language; its own
// (English, technical) text only as a detail, where it says something the translation can't.

import { ApiError } from "./api";
import { isKey, type Key } from "./i18n";

type T = (key: Key, vars?: Record<string, string | number>) => string;

// codes whose message names what was wrong (a style field, a speaker): it is kept as the detail
const WITH_DETAIL = new Set(["not_youtube", "cannot_retouch", "no_speaker", "invalid_speakers", "invalid_style"]);

export function errorText(err: unknown, t: T): string {
  if (err instanceof ApiError && err.status === 0) return t("unreachable");
  if (err instanceof ApiError && err.code && isKey(`err_${err.code}`)) {
    const text = t(`err_${err.code}` as Key, err.params);
    return WITH_DETAIL.has(err.code) ? `${text} ${t("detail", { d: err.message })}` : text;
  }
  // a code this page doesn't know yet, or no code (a proxy's error page, FastAPI's own validation)
  return `${t("err_unknown")} ${t("detail", { d: err instanceof Error ? err.message : String(err) })}`;
}

/** A failed dub's message: a common failure (its code) in the page's language, the English text
 *  as its detail; any other failure as the server said it. */
export function jobErrorText(error: string | null, code: string | null | undefined,
  params: Record<string, string> | null | undefined, t: T): { text: string; detail: string | null } {
  const key = `err_phase_${code}`;
  if (code && isKey(key)) return { text: t(key as Key, params ?? {}), detail: error };
  return { text: error ?? t("err_unknown"), detail: null };
}
