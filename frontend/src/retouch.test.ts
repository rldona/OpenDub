import { describe, expect, it } from "vitest";
import { retouchQueue } from "./retouch";

describe("retouch queue", () => {
  it("joins pending edits and takes, once each and in order", () => {
    expect(retouchQueue([5, 2], new Set([2, 9]), false)).toEqual([2, 5, 9]);
  });
  it("is empty when the clips were deleted to save space", () => {
    expect(retouchQueue([5], new Set([2]), true)).toEqual([]);
  });
});
