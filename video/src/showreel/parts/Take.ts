import { still } from "../theme";

// Map a chapter frame onto a capture: hold frame `first` until `start`, then play one capture frame per
// reel frame (both run at 60 fps), and hold the last frame at the end.
export const playhead = (frame: number, start: number, first: number, last: number) =>
  Math.min(last, Math.max(first, first + Math.round(frame - start)));

export const shot = (take: string, index: number) => still(`${take}/${String(index).padStart(4, "0")}.png`);
