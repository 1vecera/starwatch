import { Easing, useCurrentFrame } from "remotion";
import { clamp01, pop, ramp } from "../theme";
import { vBlur } from "./Blur";

// Kinetic type: each word (or letter) rises out of its own baseline mask on its frame with a spring
// that slightly overshoots, smears vertically while it moves, and leaves upward through the same mask.
const MASK: React.CSSProperties = {
  display: "inline-block",
  overflow: "hidden",
  verticalAlign: "bottom",
  paddingTop: "0.24em",
  paddingBottom: "0.2em",
  marginTop: "-0.24em",
  marginBottom: "-0.2em",
};

const EXIT = Easing.in(Easing.cubic);

export const rise = (frame: number, at: number, out: number) => {
  const inn = 1 - pop(frame, at, 1.15, 1.25);
  const leave = ramp(frame, out, out + 8, EXIT);
  return inn * 1.35 - leave * 1.45;
};

export type W = { text: string; at: number };

const Mask: React.FC<{ size: number; lineHeight: React.CSSProperties["lineHeight"]; right: string; children: React.ReactNode }> = ({ size, lineHeight, right, children }) => (
  <span style={{ ...MASK, fontSize: size, lineHeight, paddingLeft: "0.04em", paddingRight: "0.04em", marginLeft: "-0.04em", marginRight: right }}>{children}</span>
);

export const Words: React.FC<{ words: W[]; out?: number; style: React.CSSProperties; gap?: number }> = ({ words, out = 1e9, style, gap = 0.24 }) => {
  const frame = useCurrentFrame();
  const size = Number(style.fontSize ?? 100);
  return (
    <span style={{ whiteSpace: "nowrap" }}>
      {words.map((w, i) => {
        const y = rise(frame, w.at, out);
        const speed = (y - rise(frame - 1, w.at, out)) * size;
        const hidden = frame < w.at || frame > out + 10;
        return (
          <Mask key={i} size={size} lineHeight={style.lineHeight} right={i < words.length - 1 ? `${gap - 0.04}em` : "-0.04em"}>
            <span style={{ ...style, display: "inline-block", visibility: hidden ? "hidden" : "visible", transform: `translateY(${y * 100}%)`, filter: vBlur(speed) }}>{w.text}</span>
          </Mask>
        );
      })}
    </span>
  );
};

// The same rise, one letter at a time, `step` frames apart: for the opening line only.
export const Letters: React.FC<{ text: string; at: number; step?: number; out?: number; style: React.CSSProperties }> = ({ text, at, step = 1.2, out = 1e9, style }) => {
  const frame = useCurrentFrame();
  const size = Number(style.fontSize ?? 100);
  let n = -1;
  return (
    <span style={{ whiteSpace: "nowrap" }}>
      {text.split(" ").map((word, wi, all) => (
        <span key={wi} style={{ display: "inline-block", marginRight: wi < all.length - 1 ? "0.24em" : 0, fontSize: size }}>
          {[...word].map((ch, ci) => {
            n += 1;
            const start = at + n * step;
            const leave = out + n * 0.6;
            const y = rise(frame, start, leave);
            const speed = (y - rise(frame - 1, start, leave)) * size;
            return (
              <Mask key={ci} size={size} lineHeight={style.lineHeight} right="-0.04em">
                <span style={{ ...style, display: "inline-block", visibility: frame < start || frame > leave + 10 ? "hidden" : "visible", transform: `translateY(${y * 100}%)`, filter: vBlur(speed) }}>
                  {ch}
                </span>
              </Mask>
            );
          })}
        </span>
      ))}
    </span>
  );
};

// An odometer: one value counts up from 0 to the number in `value` and each digit turns only when the
// digit below it carries, like a mechanical counter, so it never shows a figure above the target or a
// leading zero. Steps tick into place rather than creeping, and it always lands on the exact string.
const PITCH = 1.8;
const ROLL = Easing.bezier(0.16, 1, 0.3, 1);
const TICK = Easing.inOut(Easing.cubic);

const place = (v: number, p: number) => {
  const pow = 10 ** p;
  const whole = Math.floor(v / pow + 1e-9);
  const rest = v - whole * pow;
  const turn = p === 0 ? rest : clamp01(rest - (pow - 1));
  return { digit: whole % 10, turn: TICK(clamp01((turn - 0.35) / 0.65)), whole };
};

export const Odometer: React.FC<{ value: string; from: number; dur: number; out?: number; style: React.CSSProperties }> = ({ value, from, dur, out = 1e9, style }) => {
  const frame = useCurrentFrame();
  const size = Number(style.fontSize ?? 100);
  const chars = [...value];
  const digits = chars.filter((c) => /\d/.test(c));
  const target = Number(digits.join(""));
  const valueAt = (f: number) => target * ROLL(clamp01((f - from - 2) / dur));
  const v = valueAt(frame);
  const prev = valueAt(frame - 1);
  const y = rise(frame, from, out);
  const ySpeed = (y - rise(frame - 1, from, out)) * size;
  let k = -1;
  let shown = 0;
  return (
    <span style={{ ...MASK, fontSize: size, lineHeight: style.lineHeight, visibility: frame < from || frame > out + 10 ? "hidden" : "visible" }}>
      <span style={{ ...style, display: "inline-flex", alignItems: "flex-start", fontVariantNumeric: "tabular-nums", transform: `translateY(${y * 100}%)`, filter: vBlur(ySpeed) }}>
        {chars.map((ch, i) => {
          const cell: React.CSSProperties = { display: "inline-block", height: "1em", lineHeight: "1em" };
          if (!/\d/.test(ch)) return <span key={i} style={{ ...cell, opacity: shown }}>{ch === " " ? " " : ch}</span>;
          k += 1;
          const p = digits.length - 1 - k;
          const now = place(v, p);
          const before = place(prev, p);
          // A leading position stays blank until the count reaches it, and fades in as it first turns.
          shown = p === 0 || now.whole > 0 ? 1 : now.turn;
          const speed = Math.min(30, (now.whole + now.turn - (before.whole + before.turn)) * size * PITCH * 0.3);
          return (
            <span key={i} style={{ ...cell, height: "1.1em", marginBottom: "-0.1em", position: "relative", overflow: "hidden", opacity: shown }}>
              <span style={{ visibility: "hidden" }}>0</span>
              <span style={{ position: "absolute", left: 0, right: 0, top: 0, textAlign: "center", transform: `translateY(${-now.turn * PITCH}em)`, filter: vBlur(speed) }}>
                <span style={{ display: "block", height: `${PITCH}em` }}>{now.digit}</span>
                <span style={{ display: "block", height: `${PITCH}em` }}>{(now.digit + 1) % 10}</span>
              </span>
            </span>
          );
        })}
      </span>
    </span>
  );
};

// A block that wipes in behind a phrase; the phrase turns white where the block covers it. `children`
// renders the phrase in the colour it is given, twice, so both copies move identically.
export const Highlight: React.FC<{ at: number; out?: number; color: string; size: number; children: (ink: boolean) => React.ReactNode }> = ({ at, out = 1e9, color, size, children }) => {
  const frame = useCurrentFrame();
  const p = ramp(frame, at, at + 10, Easing.bezier(0.7, 0, 0.2, 1));
  // On `out` the block collapses toward its right edge as the words leave.
  const gone = ramp(frame, out, out + 8, Easing.bezier(0.7, 0, 0.2, 1));
  return (
    <span style={{ position: "relative", display: "inline-block", fontSize: size }}>
      <span
        style={{
          position: "absolute",
          left: "-0.08em",
          right: "-0.1em",
          top: "0.04em",
          bottom: "-0.06em",
          background: color,
          borderRadius: "0.06em",
          transform: `scaleX(${gone > 0 ? 1 - gone : p})`,
          transformOrigin: gone > 0 ? "100% 50%" : "0 50%",
        }}
      />
      <span style={{ position: "relative" }}>{children(true)}</span>
      <span style={{ position: "absolute", left: 0, top: 0, clipPath: `inset(-0.4em ${(1 - p) * 100}% -0.4em ${gone > 0 ? `${gone * 100}%` : "-0.3em"})` }}>{children(false)}</span>
    </span>
  );
};
