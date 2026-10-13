import { Easing, interpolate, staticFile } from "remotion";
import { loadFont } from "@remotion/fonts";

loadFont({ family: "Bricolage Grotesque", url: staticFile("fonts/BricolageGrotesque.ttf"), weight: "200 800" });
loadFont({ family: "Schibsted Grotesk", url: staticFile("fonts/SchibstedGrotesk.ttf"), weight: "400 900" });
loadFont({ family: "Sora", url: staticFile("fonts/Sora.ttf"), weight: "100 800" });

// Starwatch identity on a night surface: brand teal #0E6E6B, lifted for light on dark, ink from the app.
export const C = {
  bg: "#040B0B",
  ink: "#EEF4F4",
  ink2: "#A3B6B4",
  ink3: "#6B807E",
  ink4: "#1A2827",
  line: "rgba(238,244,244,0.14)",
  teal: "#4FCBC2",
  brand: "#0E6E6B",
  tealGlow: "rgba(79,203,194,0.5)",
};

export const DISPLAY = "'Bricolage Grotesque', 'Schibsted Grotesk', sans-serif";
export const UI = "'Schibsted Grotesk', sans-serif";
export const WORDMARK = "'Sora', sans-serif";

// One display scale (px at 1080p).
export const T = { xl: 190, l: 140, m: 96, s: 60, xs: 36 };
export const LABEL = "#8EA3A1";

// Labels: tracked capitals in Schibsted Grotesk, as the app's own small labels are set.
export const label = (size = 16, color = C.ink2): React.CSSProperties => ({
  fontFamily: UI,
  fontWeight: 650,
  fontSize: size,
  letterSpacing: "0.16em",
  textTransform: "uppercase",
  color,
  whiteSpace: "nowrap",
});

export const display = (size: number, weight = 800): React.CSSProperties => ({
  fontFamily: DISPLAY,
  fontSize: size,
  fontWeight: weight,
  letterSpacing: "-0.035em",
  lineHeight: 0.98,
  color: C.ink,
  whiteSpace: "nowrap",
  fontVariationSettings: `"opsz" 96`,
});

export const brand = (name: string) => staticFile(`showreel/brand/${name}`);
export const still = (path: string) => staticFile(`showreel/${path}`);

export const easeOut = Easing.bezier(0.16, 1, 0.3, 1);
export const easeIn = Easing.bezier(0.7, 0, 0.84, 0);
export const easeInOut = Easing.bezier(0.65, 0, 0.35, 1);

export const ramp = (
  frame: number,
  from: number,
  to: number,
  easing: (t: number) => number = easeOut,
  outFrom = 0,
  outTo = 1,
) =>
  interpolate(frame, [from, to], [outFrom, outTo], {
    easing,
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

// Damped oscillation for overshoot: 1 -> 0 while ringing.
export const ring = (t: number, frequency = 3.2, damping = 5.5) =>
  t < 0 ? 0 : Math.exp(-damping * t) * Math.sin(2 * Math.PI * frequency * t);

export const clamp01 = (v: number) => Math.min(1, Math.max(0, v));
