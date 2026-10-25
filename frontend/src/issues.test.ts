import { describe, expect, it } from "vitest";
import type { Issue } from "./api";
import { translate } from "./i18n";
import { issueClass, issueText } from "./pages/Video";

const t = (k: Parameters<typeof translate>[1], v?: Record<string, string | number>) => translate("es", k, v);
const issue = (kind: Issue["kind"], message: string): Issue => ({ id: 1, kind, message, start: 0, text: "Hola.", wav: null });

describe("issue texts", () => {
  it("reads each kind of issue in the page's language", () => {
    expect(issueText(issue("overflow", "lasts 2.50s at 1.25x, slot 2.40s (+0.10s)"), t)).toBe("No cabe: +0.10 s");
    expect(issueText(issue("floor", "did not fit even shortened, duration factor 0.62 below the 0.70 floor"), t))
      .toBe("Comprimido a 0.62, bajo el suelo");
    expect(issueText(issue("repaired", "redone by the quality check: chatterbox (seed+1)"), t)).toBe("Rehecho: otra semilla");
    expect(issueText(issue("glossary", 'glossary: "VFX" → "efectos"'), t)).toBe("Glosario: «VFX» debería ser «efectos»");
    expect(issueClass(issue("fallback", ""))).toBe("danger-text");
  });
});
