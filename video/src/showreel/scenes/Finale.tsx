import { AbsoluteFill, Img, useCurrentFrame } from "remotion";
import { Words } from "../parts/Kinetic";
import { kick, track } from "../parts/track";
import { asset, C, clamp01, easeIn, easeOut, expoOut, label, ramp, TEXT, WORDMARK } from "../theme";
import { beatAt, beatFrame as F, DURATION } from "../timing";

// The app's 3D mark (img/mark-3d.webp) spins up out of the canvas with a contour ring on every beat,
// gathers, and snaps into the lockup on the final hit. At rest the end card is the brand file itself
// (checked by StarwatchLockupCheck).
export const LOCKUP = { w: 260.9 * 3, h: 66 * 3 };
export const LOCKUP_AT = { x: Math.round(960 - (260.9 * 3) / 2), y: 330 };
export const REST = 16;
const MARK_AT = { x: LOCKUP_AT.x + 31 * 3, y: LOCKUP_AT.y + 33 * 3 };
const WORD_FROM = 62 / 260.9;

export const MarkBuild: React.FC = () => {
  const frame = useCurrentFrame();
  // Spins up out of the canvas, drifts, winds back on the last beat, then slams into the lockup.
  const m = track(frame, [
    { f: F(83.5), x: 960, y: 540, w: 40, r: -540 },
    { f: F(84.25), x: 960, y: 540, w: 760, r: -60, e: expoOut },
    { f: F(87.25), x: 960, y: 540, w: 640, r: 75 },
    { f: F(87.75), x: 960, y: 540, w: 730, r: 59, e: easeOut },
    { f: F(88), x: MARK_AT.x, y: MARK_AT.y, w: 176, r: 540, e: easeIn },
  ]);
  // Between the spin-up and the wind-back, an eighth turn snaps in on each beat with a kick (a quarter
  // turn would land on the same pose: the mark has four-fold symmetry).
  const turnAt = (f: number) => {
    const b = beatAt(f);
    if (b < 84.25 || b >= 87.25) return null;
    return -60 + 45 * (Math.floor(b) - 85 + expoOut(Math.min(1, (f - F(Math.floor(b))) / 8)));
  };
  const turn = turnAt(frame);
  if (turn !== null) {
    m.r = turn;
    m.w *= 1 + 0.14 * kick(frame, F(Math.floor(beatAt(frame))), 10);
  }
  const spin = turn !== null && turnAt(frame - 1) !== null ? turn - (turnAt(frame - 1) as number) : 0;
  const fade = 1 - ramp(frame, F(88) - 1, F(88) + 5, (t) => t);
  const rings = Array.from({ length: 4 }, (_, i) => {
    const t = clamp01((frame - F(84 + i)) / 40);
    return t > 0 && t < 1 ? { r: m.w * 0.42 + 900 * expoOut(t), o: 0.5 * (1 - t) } : null;
  });
  if (fade <= 0) return null;
  return (
    <AbsoluteFill>
      <svg width={1920} height={1080} style={{ position: "absolute", inset: 0 }}>
        {rings.map((ring, i) => (ring ? <circle key={i} cx={960} cy={540} r={ring.r} fill="none" stroke={C.brand} strokeWidth={2.5} strokeOpacity={ring.o} /> : null))}
      </svg>
      {/* While it snaps, two ghosts trail the turn: the mark's own motion blur. */}
      {(spin > 3 ? [[12, 0.15], [6, 0.35], [0, 1]] : [[0, 1]]).map(([back, o]) => (
        <Img
          key={back}
          src={asset("img/mark-3d.webp")}
          style={{
            position: "absolute",
            left: m.x - m.w / 2,
            top: m.y - (m.w * 640) / 619 / 2,
            width: m.w,
            height: (m.w * 640) / 619,
            transform: `rotate(${m.r - back}deg)`,
            opacity: fade * o,
          }}
        />
      ))}
    </AbsoluteFill>
  );
};

// The hit: two contour rings burst from the mark as it lands in the lockup.
const Burst: React.FC<{ frame: number }> = ({ frame }) => (
  <svg width={1920} height={1080} style={{ position: "absolute", inset: 0, pointerEvents: "none" }}>
    {[0, 6].map((delay) => {
      const t = clamp01((frame - delay) / 36);
      return t > 0 && t < 1 ? <circle key={delay} cx={MARK_AT.x} cy={MARK_AT.y} r={90 + 1100 * expoOut(t)} fill="none" stroke={C.brand} strokeWidth={3} strokeOpacity={0.55 * (1 - t)} /> : null;
    })}
  </svg>
);

export const EndCard: React.FC<{ start?: number }> = ({ start = F(88) }) => {
  const frame = useCurrentFrame() - start;
  const resting = frame >= REST;
  const t = clamp01(frame / REST);
  const wipe = expoOut(t);
  const punch = 1 + 0.12 * (1 - expoOut(t));
  const fade = ramp(frame, DURATION - start - 22, DURATION - start - 2, (x) => x, 1, 0);
  const at = (beats: number) => F(88 + beats) - F(88);
  return (
    <AbsoluteFill style={{ opacity: fade }}>
      {frame >= 0 && frame < 50 ? <Burst frame={frame} /> : null}
      <Img
        src={asset("brand/lockup.svg")}
        style={{
          position: "absolute",
          left: LOCKUP_AT.x,
          top: LOCKUP_AT.y,
          width: LOCKUP.w,
          height: LOCKUP.h,
          opacity: resting ? 1 : ramp(frame, -1, 3, (x) => x),
          clipPath: resting ? undefined : `inset(-10% ${(1 - WORD_FROM) * 100 * (1 - wipe)}% -10% -10%)`,
          transform: resting ? undefined : `scale(${punch})`,
          transformOrigin: `${MARK_AT.x - LOCKUP_AT.x}px ${MARK_AT.y - LOCKUP_AT.y}px`,
        }}
      />
      <div style={{ position: "absolute", left: 0, right: 0, top: 596, textAlign: "center" }}>
        <Words words={[{ text: "starwatch.danielvecera.com", at: start + at(0.75) }]} style={{ fontFamily: WORDMARK, fontWeight: 700, fontSize: 50, color: C.label, letterSpacing: "-0.01em" }} />
      </div>
      <div style={{ position: "absolute", left: 0, right: 0, top: 690, textAlign: "center" }}>
        <Words words={[{ text: "Open source: github.com/1vecera/starwatch", at: start + at(1.5) }]} style={label(30)} />
      </div>
      <div style={{ position: "absolute", left: 0, right: 0, top: 738, textAlign: "center" }}>
        <Words words={[{ text: "Made by Daniel Večeřa, Prague", at: start + at(2) }]} style={label(30, C.label3)} />
      </div>
      <div style={{ position: "absolute", left: 0, right: 0, top: 1000, textAlign: "center", fontFamily: TEXT, fontSize: 21, color: C.label3, opacity: ramp(frame, at(3), at(3) + 14, easeOut) }}>
        App footage: real captures of the live app
      </div>
    </AbsoluteFill>
  );
};
