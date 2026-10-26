import { describe, expect, it } from "vitest";
import { pickOptions, togglePick } from "./catalog";

describe("togglePick", () => {
  it("adds and removes engines, in the catalogue's order", () => {
    expect(togglePick(["cosyvoice"], "chatterbox")).toEqual(["chatterbox", "cosyvoice"]);
    expect(togglePick(["chatterbox", "cosyvoice"], "indextts")).toEqual(["chatterbox", "indextts", "cosyvoice"]);
    expect(togglePick(["chatterbox", "cosyvoice"], "chatterbox")).toEqual(["cosyvoice"]);
  });

  it("keeps Automatic apart and never leaves nothing picked", () => {
    expect(togglePick(["chatterbox", "indextts"], "auto")).toEqual(["auto"]);
    expect(togglePick(["auto"], "indextts")).toEqual(["indextts"]);
    expect(togglePick(["cosyvoice"], "cosyvoice")).toEqual(["cosyvoice"]);
  });
});

describe("pickOptions", () => {
  it("dubs with the first and queues the rest", () => {
    expect(pickOptions(["chatterbox", "indextts", "cosyvoice"])).toEqual({ engine: "chatterbox", then: ["indextts", "cosyvoice"] });
    expect(pickOptions(["auto"])).toEqual({ engine: "auto", then: [] });
  });
});
