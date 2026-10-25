import { describe, expect, it } from "vitest";
import { browserLang } from "./prefs";

describe("browserLang", () => {
  it("is Spanish when the browser asks for any Spanish first, English otherwise", () => {
    expect(browserLang(["es-ES", "en"])).toBe("es");
    expect(browserLang(["es-419"])).toBe("es");
    expect(browserLang(["fr-FR", "es"])).toBe("es"); // the first of the two the page speaks
    expect(browserLang(["en-GB", "es"])).toBe("en");
    expect(browserLang(["de"])).toBe("en");
    expect(browserLang([])).toBe("en");
  });
});
