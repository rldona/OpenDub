import { describe, expect, it } from "vitest";
import { ApiError } from "./api";
import { errorText } from "./errors";
import { translate, type Key } from "./i18n";

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
