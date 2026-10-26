import { describe, expect, it } from "vitest";
import { ApiError } from "./api";
import { errorText, jobErrorText } from "./errors";
import { isKey, translate, type Key } from "./i18n";

const es = (key: Key, vars?: Record<string, string | number>) => translate("es", key, vars);

describe("errorText", () => {
  it("says a known error in the page's language, with its parameters", () => {
    const err = new ApiError("Another OpenDub process is working on this video (opendub dub)", 409, "busy",
      { holder: "opendub dub" });
    expect(errorText(err, es)).toBe(
      "Otro proceso de OpenDub (opendub dub) está trabajando con este vídeo: inténtalo cuando acabe.");
  });

  it("keeps the technical text only as a detail where it says what was wrong", () => {
    const err = new ApiError("variant must be one of es-ES, es-MX (not 'x')", 422, "invalid_style");
    expect(errorText(err, es)).toBe("Ese estilo no es válido. Detalle: variant must be one of es-ES, es-MX (not 'x')");
    expect(errorText(new ApiError("No such dub", 404, "no_dub"), es)).toBe("Ese doblaje no existe.");
  });

  it("falls back to a generic sentence for unknown codes and plain errors", () => {
    expect(errorText(new ApiError("Teapot", 418, "teapot"), es)).toBe("Algo ha fallado. Detalle: Teapot");
    expect(errorText(new ApiError("Bad Gateway", 502), es)).toBe("Algo ha fallado. Detalle: Bad Gateway");
    expect(errorText(new ApiError("unreachable", 0), es)).toContain("No hay conexión");
  });
});

describe("jobErrorText", () => {
  // the codes src/opendub/errors.py raises: each has its text in both languages
  const CODES = ["youtube_blocked", "youtube_unreachable", "claude_unreachable", "ollama_unreachable",
    "engine_missing", "diarizer_missing", "clips_deleted"];

  it("has a text for every phase error the server raises", () => {
    for (const code of CODES) expect(isKey(`err_phase_${code}`), code).toBe(true);
  });

  it("says a common failure in Spanish, the server's English as the detail", () => {
    const got = jobErrorText("Can't reach Claude (api.anthropic.com) to translate: [Errno 101] Network is unreachable.",
      "claude_unreachable", { host: "api.anthropic.com" }, es);
    expect(got.text).toBe("No hay conexión con Claude (api.anthropic.com) para traducir. ¿Hay internet?");
    expect(got.detail).toContain("Network is unreachable");
    expect(jobErrorText("…", "engine_missing", { engine: "CosyVoice 3", cmd: "uv run opendub setup-engine cosyvoice" }, es)
      .text).toBe("CosyVoice 3 no está instalado. Instálalo con: uv run opendub setup-engine cosyvoice");
  });

  it("keeps any other failure as the server said it", () => {
    expect(jobErrorText("YouTube download failed: Video unavailable", null, null, es))
      .toEqual({ text: "YouTube download failed: Video unavailable", detail: null });
  });
});
