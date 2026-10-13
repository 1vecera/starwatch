import { Easing, interpolate, staticFile } from "remotion";
import { loadFont } from "@remotion/fonts";

loadFont({ family: "Schibsted Grotesk", url: staticFile("fonts/SchibstedGrotesk.ttf"), weight: "400 900" });
loadFont({ family: "Sora", url: staticFile("fonts/Sora.ttf"), weight: "100 800" });
loadFont({ family: "Bricolage Grotesque", url: staticFile("fonts/BricolageGrotesque.ttf"), weight: "200 800" });

// The app's own page (app/web/ds.css): slate canvas, white surfaces, one teal, slate shadows, never a glow.
export const C = {
  canvas: "#F2F7F7",
  surface: "#FFFFFF",
  label: "#0F172A",
  label2: "#475569",
  label3: "#5B6A7E",
  brand: "#0E6E6B",
  brandSoft: "#E3F1F0",
  hairline: "rgba(22,37,36,0.10)",
};
// --elev-3 from ds.css: a contact shadow plus a soft ambient one.
export const ELEV3 = "0 2px 4px rgb(15 23 42 / .05), 0 12px 24px -6px rgb(15 23 42 / .10), 0 32px 64px -16px rgb(15 23 42 / .20)";

export const TEXT = "'Schibsted Grotesk', sans-serif";
export const WORDMARK = "'Sora', sans-serif";
// The app's display face, set like its welcome h1: weight 720, tracking -0.036em, optical size at its largest.
export const DISPLAY = "'Bricolage Grotesque', sans-serif";
export const display = (size: number, color: string = C.label, weight = 720): React.CSSProperties => ({
  fontFamily: DISPLAY,
  fontSize: size,
  fontWeight: weight,
  fontVariationSettings: "'opsz' 96",
  letterSpacing: "-0.036em",
  lineHeight: 0.98,
  color,
  whiteSpace: "nowrap",
});
export const label = (size: number, color: string = C.label2, weight = 560): React.CSSProperties => ({
  fontFamily: TEXT,
  fontSize: size,
  fontWeight: weight,
  letterSpacing: "-0.005em",
  color,
  whiteSpace: "nowrap",
});

export const asset = (path: string) => staticFile(`showreel/${path}`);

export const easeOut = Easing.bezier(0.16, 1, 0.3, 1);
export const easeIn = Easing.bezier(0.7, 0, 0.84, 0);
export const easeInOut = Easing.bezier(0.65, 0, 0.35, 1);
export const expoOut = Easing.bezier(0.19, 1, 0.22, 1);

export const ramp = (frame: number, from: number, to: number, easing: (t: number) => number = easeOut, outFrom = 0, outTo = 1) =>
  interpolate(frame, [from, to], [outFrom, outTo], { easing, extrapolateLeft: "clamp", extrapolateRight: "clamp" });

// A damped spring from 0 to 1 that starts at `from` (frames); overshoots once and settles.
export const pop = (frame: number, from: number, stiffness = 1, damping = 1) => {
  const t = (frame - from) / 60;
  if (t <= 0) return 0;
  const w = 15 * stiffness;
  const z = 0.42 * damping;
  return 1 - Math.exp(-z * w * t) * Math.cos(w * Math.sqrt(1 - z * z) * t);
};

export const lerp = (a: number, b: number, t: number) => a + (b - a) * t;
export const clamp01 = (t: number) => Math.min(1, Math.max(0, t));
