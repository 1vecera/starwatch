import { C, label, ramp } from "../theme";
import { scramble } from "./Scramble";

// An annotation that never covers captured pixels: a bracket just outside the app window spans the
// element's extent along that edge, and a leader runs out into the margin to the label.
export const Callout: React.FC<{
  side: "left" | "right" | "top" | "bottom";
  edge: number; // the window edge coordinate (x for left/right, y for top/bottom)
  from: number; // the element's extent along the edge
  to: number;
  text: string;
  frame: number;
  at: number;
  until?: number;
  reach?: number; // leader length into the margin
  accent?: boolean;
  width?: number; // labels at the sides wrap within this width
}> = ({ side, edge, from, to, text, frame, at, until = 1e9, reach = 40, accent = false, width = 320 }) => {
  const draw = ramp(frame, at, at + 10);
  const out = ramp(frame, until, until + 6, (t) => t, 1, 0);
  const opacity = draw * out;
  if (opacity <= 0) return null;
  const color = accent ? C.teal : C.ink;
  const shown = scramble(text, ramp(frame, at + 4, at + 11), text, frame);
  const horizontal = side === "left" || side === "right";
  const sign = side === "right" || side === "bottom" ? 1 : -1;
  const gap = 12;
  const b = edge + sign * gap; // bracket line
  const mid = (from + to) / 2;
  const half = ((to - from) / 2) * Math.min(1, draw * 1.6);
  const lead = reach * Math.max(0, draw * 2 - 1);
  const tip = b + sign * lead;
  const tick = 6 * sign;
  const path = horizontal
    ? `M${b - tick},${mid - half} L${b},${mid - half} L${b},${mid + half} L${b - tick},${mid + half} M${b},${mid} L${tip},${mid}`
    : `M${mid - half},${b - tick} L${mid - half},${b} L${mid + half},${b} L${mid + half},${b - tick} M${mid},${b} L${mid},${tip}`;
  const text_: React.CSSProperties = horizontal
    ? { top: mid - 12, width, whiteSpace: "normal", lineHeight: 1.45, ...(sign > 0 ? { left: tip + 10 } : { right: 1920 - tip + 10, textAlign: "right" }) }
    : { left: mid, transform: "translateX(-50%)", ...(sign > 0 ? { top: tip + 8 } : { bottom: 1080 - tip + 8 }) };
  return (
    <div style={{ position: "absolute", inset: 0, opacity, pointerEvents: "none" }}>
      <svg width={1920} height={1080} style={{ position: "absolute", inset: 0 }}>
        <path d={path} fill="none" stroke={accent ? C.teal : "rgba(238,244,244,0.7)"} strokeWidth={1.4} />
        <circle cx={horizontal ? tip : mid} cy={horizontal ? mid : tip} r={2.4} fill={color} />
      </svg>
      <div style={{ ...label(17, color), position: "absolute", ...text_ }}>{shown}</div>
    </div>
  );
};
