/** The sentences a retouch speaks again: the edits not heard yet and the takes asked for, in order;
 * none when the voice clips were deleted to save space (the video must be dubbed again first). */
export function retouchQueue(pending: number[], takes: Set<number>, clipsGone: boolean): number[] {
  return clipsGone ? [] : [...new Set([...pending, ...takes])].sort((a, b) => a - b);
}
