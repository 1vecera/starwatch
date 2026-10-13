import { Easing, interpolate, staticFile } from "remotion";
import { loadFont } from "@remotion/fonts";

loadFont({ family: "Schibsted Grotesk", url: staticFile("fonts/SchibstedGrotesk.ttf"), weight: "400 900" });
loadFont({ family: "Sora", url: staticFile("fonts/Sora.ttf"), weight: "100 800" });

// The app's own page (app/web/ds.css): slate canvas, white surfaces, one teal, slate shadows, never a glow.
export const C = {
  canvas: "#F2F7F7",
  surface: "#FFFFFF",
  label: "#0F172A",
  label2: "#475569",
  label3: "#5B6A7E",
  brand: "#0E6E6B",
  hairline: "rgba(15,23,42,0.10)",
};
// --elev-3 from ds.css: a contact shadow plus a soft ambient one.
export const ELEV3 = "0 2px 4px rgb(15 23 42 / .05), 0 12px 24px -6px rgb(15 23 42 / .10), 0 32px 64px -16px rgb(15 23 42 / .20)";

export const TEXT = "'Schibsted Grotesk', sans-serif";
export const WORDMARK = "'Sora', sans-serif";

export const asset = (path: string) => staticFile(`showreel/${path}`);

export const easeOut = Easing.bezier(0.16, 1, 0.3, 1);
export const easeInOut = Easing.bezier(0.65, 0, 0.35, 1);

export const ramp = (frame: number, from: number, to: number, easing: (t: number) => number = easeOut, outFrom = 0, outTo = 1) =>
  interpolate(frame, [from, to], [outFrom, outTo], { easing, extrapolateLeft: "clamp", extrapolateRight: "clamp" });
