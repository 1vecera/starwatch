import { Easing, interpolate, useCurrentFrame } from "remotion";
import { C } from "../theme";

// The star mark's four blades (app/web/brand/mark-v2.svg, viewBox -32 -32 64 64): left, bottom, right, top.
export const BLADES = [
  "M-30,0L-10.06,8.55L-6.77,-1.31L-5.21,-0.79L-0.91,-5.09L-10.59,-8.32Z",
  "M0,30L8.55,10.06L-1.31,6.77L-0.79,5.21L-5.09,0.91L-8.32,10.59Z",
  "M30,0L10.06,-8.55L6.77,1.31L5.21,0.79L0.91,5.09L10.59,8.32Z",
  "M0,-30L-8.55,-10.06L1.31,-6.77L0.79,-5.21L5.09,-0.91L8.32,-10.59Z",
];

export type BladePose = { x: number; y: number; r: number; s: number };

// The mark at (cx, cy); `unit` is px per mark unit (the mark spans 60 units). Each blade can be posed
// on its own, in mark units, so the blades can fly in and lock together.
export const Mark: React.FC<{ cx: number; cy: number; unit: number; color?: string; pose?: (i: number) => BladePose; rotate?: number; style?: React.CSSProperties }> = ({
  cx,
  cy,
  unit,
  color = C.brand,
  pose,
  rotate = 0,
  style,
}) => {
  const half = 32 * unit;
  return (
    <svg
      width={half * 2}
      height={half * 2}
      viewBox="-32 -32 64 64"
      style={{ position: "absolute", left: cx - half, top: cy - half, overflow: "visible", ...style }}
    >
      <g transform={`rotate(${rotate})`}>
        {BLADES.map((d, i) => {
          const p = pose ? pose(i) : { x: 0, y: 0, r: 0, s: 1 };
          return <path key={i} d={d} fill={color} transform={`translate(${p.x} ${p.y}) rotate(${p.r}) scale(${p.s})`} />;
        })}
      </g>
    </svg>
  );
};

// The brand wipe: one blade of the mark, hundreds of times its size, sweeps across the frame tip first.
// Between `sweepCovered` frames it covers the whole frame, so scenes swap under it at `sweepSwap`.
const K = 300;
const travel = (u: number) => interpolate(u, [0, 1], [-150, 1920 + 29 * K + 150]);
const ease = Easing.inOut(Easing.sin);
const tipAt = (frame: number, at: number, dur: number) => travel(ease(Math.min(1, Math.max(0, (frame - at) / dur))));

export const sweepSwap = (at: number, dur: number) => {
  for (let f = at; f <= at + dur; f++) if (tipAt(f, at, dur) >= 4400) return f;
  return at + Math.round(dur / 2);
};

export const BladeSweep: React.FC<{ at: number; dur: number; color?: string; flip?: boolean }> = ({ at, dur, color = C.brand, flip = false }) => {
  const frame = useCurrentFrame();
  if (frame < at || frame > at + dur) return null;
  const x = tipAt(frame, at, dur);
  // Tip of the top blade is (0, -30); rotate it to point along +x and put the tip at x.
  const tx = flip ? 1920 - x : x;
  return (
    <svg width={1920} height={1080} style={{ position: "absolute", inset: 0, overflow: "visible" }}>
      <g transform={`translate(${tx} 540) rotate(${flip ? -96 : 84}) translate(0 ${30 * K}) scale(${K})`}>
        <path d={BLADES[3]} fill={color} />
      </g>
    </svg>
  );
};
