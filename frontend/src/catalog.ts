// What the page says about each cloning engine: name, license, where it runs and its
// benchmark figures (docs/v2-plan.md, docs/bench/results), per test voice.
import type { Engine } from "./api";
import type { Key } from "./i18n";

export interface VoiceFigures {
  cer: number; // character error rate
  p_es: number; // whisper's probability that it is Spanish
  ecapa: number; // likeness to the original speaker
  cps: number; // characters per second at its natural pace
}

export interface EngineInfo {
  id: Engine;
  name: string;
  short: string;
  license: string;
  note: Key;
  inside: boolean; // runs in OpenDub's own process (else in its own venv)
  male: VoiceFigures;
  female: VoiceFigures;
  rtf: number;
  vram: number;
  fits: number; // of the 42 dub segments, without atempo
}

export const ENGINES: EngineInfo[] = [
  {
    id: "chatterbox", name: "Chatterbox V3", short: "Chatterbox", license: "MIT", note: "note_chatterbox", inside: true,
    male: { cer: 0.021, p_es: 0.992, ecapa: 0.539, cps: 14.8 }, female: { cer: 0.005, p_es: 0.997, ecapa: 0.533, cps: 13.4 },
    rtf: 0.33, vram: 3.6, fits: 30,
  },
  {
    id: "indextts", name: "IndexTTS-2.5", short: "IndexTTS", license: "bilibili", note: "note_indextts", inside: false,
    male: { cer: 0.016, p_es: 0.955, ecapa: 0.568, cps: 11.3 }, female: { cer: 0.013, p_es: 0.993, ecapa: 0.598, cps: 11.2 },
    rtf: 0.28, vram: 7.4, fits: 41,
  },
  {
    id: "cosyvoice", name: "CosyVoice 3", short: "CosyVoice", license: "Apache 2.0", note: "note_cosyvoice", inside: false,
    male: { cer: 0.016, p_es: 0.996, ecapa: 0.529, cps: 16.7 }, female: { cer: 0.0, p_es: 0.995, ecapa: 0.588, cps: 15.9 },
    rtf: 0.34, vram: 3.6, fits: 42,
  },
];

export const AUTO_F0_HZ = 165; // tts.AUTO_F0_HZ: below it Automatic picks IndexTTS

export function engineInfo(id: string | null | undefined): EngineInfo | undefined {
  return ENGINES.find((e) => e.id === id);
}

export function engineShort(id: string | null | undefined): string {
  if (id === "edge") return "edge-tts";
  return engineInfo(id)?.short ?? id ?? "—";
}

export const STOCK_VOICES = ["es-ES-AlvaroNeural", "es-ES-ElviraNeural", "es-MX-JorgeNeural", "es-MX-DaliaNeural"];
