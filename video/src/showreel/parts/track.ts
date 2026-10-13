import { Easing } from "remotion";
import { clamp01, easeInOut } from "../theme";

// Keyframes on absolute frames: every numeric field eases between neighbouring keys. A key's `e` sets
// the easing of the segment that ends on it.
type Ease = (t: number) => number;
export type Key = { f: number; e?: Ease; [field: string]: number | Ease | undefined };

export function track(frame: number, keys: Key[]): Record<string, number> {
  const fields = (k: Key) => Object.keys(k).filter((name) => name !== "f" && name !== "e");
  const values = (k: Key) => Object.fromEntries(fields(k).map((name) => [name, k[name] as number]));
  if (frame <= keys[0].f) return values(keys[0]);
  for (let i = 1; i < keys.length; i++) {
    const a = keys[i - 1];
    const b = keys[i];
    if (frame <= b.f) {
      const t = (b.e ?? easeInOut)((frame - a.f) / Math.max(1, b.f - a.f));
      return Object.fromEntries(fields(b).map((name) => [name, ((a[name] as number) ?? 0) + ((b[name] as number) - ((a[name] as number) ?? 0)) * t]));
    }
  }
  return values(keys[keys.length - 1]);
}

// A decaying kick for punches and shakes: 1 on `at`, gone after `len` frames.
export const kick = (frame: number, at: number, len = 14) => (frame < at || frame > at + len ? 0 : (1 - (frame - at) / len) ** 2);

// A whip pan centred on `center`: 0 → 1 over `len` frames, fastest on the beat itself. The outgoing
// layer sits at -1920·w and the incoming one at 1920·(1 − w), so both move as one camera.
const WHIP = Easing.bezier(0.75, 0, 0.25, 1);
export const whip = (frame: number, center: number, len = 16) => WHIP(clamp01((frame - (center - len / 2)) / len));
