import { random } from "remotion";

const GLYPHS = "ABCDEFGHJKLMNPQRSTUVWXYZ0123456789#%&*+/<>=";

// Reveal text left to right; characters not yet settled flicker through glyphs.
export const scramble = (text: string, progress: number, seed: string, frame: number, spread = 0.35) => {
  const n = text.length;
  return text
    .split("")
    .map((ch, i) => {
      if (ch === " " || ch === "·" || ch === "/") return ch;
      const settle = (i / Math.max(1, n)) * (1 - spread) + spread;
      if (progress >= settle) return ch;
      if (progress < settle - spread) return progress <= 0 ? "" : " ";
      const r = random(`${seed}-${i}-${Math.floor(frame / 2)}`);
      return GLYPHS[Math.floor(r * GLYPHS.length)];
    })
    .join("");
};
