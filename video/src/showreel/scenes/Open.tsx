import { AbsoluteFill, Easing, useCurrentFrame } from "remotion";
import { Letters, Words } from "../parts/Kinetic";
import { Mark } from "../parts/Mark";
import { track } from "../parts/track";
import { C, clamp01, display, easeOut, expoOut, pop, ramp } from "../theme";
import { beatFrame as F } from "../timing";

export const LOCK = F(1.5);
export const OPEN_OUT = F(5.25);
const FROM = [
  [-1, 0],
  [0, 1],
  [1, 0],
  [0, -1],
];

// The opening: the mark's four blades fly in from the four sides and lock together on the beat, the
// mark steps up over the app's own tagline, which rises letter by letter, then leaves; the camera dives
// through the mark itself, its blades sweeping the frame as the wall of posts lands behind them.
export const Open: React.FC = () => {
  const frame = useCurrentFrame();
  const rings = [0, 7].map((delay) => {
    const t = clamp01((frame - LOCK - delay) / 34);
    return t > 0 && t < 1 ? { r: 60 + 760 * expoOut(t), o: 0.45 * (1 - t) } : null;
  });
  return (
    <AbsoluteFill>
      <svg width={1920} height={1080} style={{ position: "absolute", inset: 0 }}>
        {rings.map((ring, i) => (ring ? <circle key={i} cx={960} cy={540} r={ring.r} fill="none" stroke={C.brand} strokeWidth={2.5} strokeOpacity={ring.o} /> : null))}
      </svg>
      <div style={{ position: "absolute", left: 150, top: 318 }}>
        <Letters text="Who’s being heard." at={F(2.25)} step={1.3} out={OPEN_OUT} style={display(176)} />
      </div>
      <div style={{ position: "absolute", left: 150, top: 512 }}>
        <Words words={[{ text: "Not just", at: F(4) }, { text: "who’s talking.", at: F(4.5) }]} out={OPEN_OUT + 4} style={display(176, C.brand)} />
      </div>
    </AbsoluteFill>
  );
};

// The mark, drawn over the wall so the dive through it reads: its blades cover the frame around beat
// 6.75 and clear as the wall settles.
const DIVE = Easing.bezier(0.9, 0, 1, 1);
export const OpenMark: React.FC = () => {
  const frame = useCurrentFrame();
  const pose = (i: number) => {
    const start = 2 + i * 3;
    const d = 1 - expoOut(clamp01((frame - start) / (LOCK - start)));
    return { x: FROM[i][0] * 260 * d, y: FROM[i][1] * 260 * d, r: -200 * d, s: 1 + 1.6 * d };
  };
  const squash = frame >= LOCK ? 1 + 0.16 * (1 - pop(frame, LOCK, 1.4, 0.9)) : 1;
  const m = track(frame, [
    { f: F(2), x: 960, y: 540, u: 4.4, r: 0 },
    { f: F(2.75), x: 206, y: 236, u: 1.6, r: 90, e: expoOut },
    { f: F(5.25), x: 206, y: 236, u: 1.6, r: 90 },
    { f: F(5.6), x: 214, y: 242, u: 1.36, r: 80, e: easeOut },
    { f: F(6.75), x: 420, y: 360, u: 64, r: 270, e: DIVE },
  ]);
  return (
    <AbsoluteFill>
      <Mark cx={m.x} cy={m.y} unit={m.u * squash} pose={pose} rotate={m.r} style={{ opacity: 1 - ramp(frame, F(6.75), F(7.05), (t) => t) }} />
    </AbsoluteFill>
  );
};
