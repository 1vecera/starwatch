import { AbsoluteFill, Img, useCurrentFrame } from "remotion";
import { vBlur } from "../parts/Blur";
import { Words } from "../parts/Kinetic";
import { Stage, transformOf } from "../parts/Stage";
import { track } from "../parts/track";
import { asset, C, clamp01, DISPLAY, easeIn, expoOut, label, ramp } from "../theme";
import { beatFrame as F } from "../timing";

// The welcome screen's wall, as the app builds it: the 48 most-viewed posts in columns that scroll at
// different speeds. Each tile is an element screenshot of the live page (capture/capture.mjs, take tiles).
const COLS = 10;
const ROWS = 6;
const TW = 230;
const TH = 288;
const GAP = 18;
const LOOP = ROWS * (TH + GAP);
const SPEED = [3.1, 2.4, 3.6, 2.7, 3.3, 2.5, 3.0, 2.8, 3.4, 2.6];
const PHASE = [0, 0.37, 0.62, 0.18, 0.81, 0.44, 0.07, 0.55, 0.29, 0.9];
const tile = (col: number, row: number) => asset(`tiles/${String(((col % 8) + 8 * row + (col >= 8 ? 3 : 0)) % 48).padStart(4, "0")}.png`);

const Column: React.FC<{ col: number; frame: number }> = ({ col, frame }) => {
  const start = F(6) + col * 1.6;
  const land = (f: number) => (1 - expoOut(clamp01((f - start) / 42))) * (col % 2 ? -2300 : 2300);
  // The scroll wraps every LOOP pixels; the blur reads the unwrapped motion so a wrap never smears.
  const travel = (f: number) => (f - F(6)) * SPEED[col] * (col % 2 ? 1 : -1);
  const scroll = (f: number) => (((travel(f) + PHASE[col] * LOOP) % LOOP) + LOOP) % LOOP;
  const y = land(frame) - scroll(frame);
  const speed = land(frame) - land(frame - 1) - (travel(frame) - travel(frame - 1));
  return (
    <div style={{ position: "absolute", left: (col - COLS / 2) * (TW + GAP), top: -LOOP, width: TW, transform: `translateY(${y}px)`, filter: vBlur(speed) }}>
      {Array.from({ length: ROWS * 3 }, (_, i) => (
        <Img key={i} src={tile(col, i % ROWS)} style={{ display: "block", width: TW, height: TH, marginBottom: GAP, borderRadius: 8 }} />
      ))}
    </div>
  );
};

// The posts become the numbers: each figure set huge in the app's display face, filled with the mosaic
// of the same 48 tiles scrolling like the wall, while the wall washes back behind it. 12,595 slams in
// from the camera and flies back through it; 5,405 (the tiles under the one teal) arrives from behind
// as it passes, and flies through in turn before the wall does.
const POSTS = { at: F(8.75), out: F(11.9) };
const CANDIDATES = { at: F(11.9) + 6, out: F(14.5) };

const FillNumber: React.FC<{
  frame: number;
  at: number;
  out: number;
  from: number;
  to: number;
  behind?: boolean;
  tint?: string;
  stroke: string;
  label: { text: string; at: number }[];
}> = ({ frame, at, out, from, to, behind = false, tint, stroke, label: words }) => {
  const inT = expoOut(clamp01((frame - at) / 16));
  const outT = easeIn(clamp01((frame - out) / 12));
  const count = Math.round(from + (to - from) * expoOut(clamp01((frame - at - 2) / 26)));
  const kick = frame >= at + 22 ? Math.max(0, 1 - (frame - at - 22) / 12) ** 2 : 0;
  const s = (behind ? 0.25 + 0.75 * inT : 2.2 - 1.2 * inT) * (1 + 0.05 * kick) * (1 + 6 * outT);
  if (frame < at || outT >= 1) return null;
  const mosaic = `url(${asset("tiles/mosaic.jpg")})`;
  return (
    <AbsoluteFill style={{ alignItems: "center", justifyContent: "center", flexDirection: "column", opacity: clamp01((frame - at) / 4) * (1 - outT), transform: `scale(${s})` }}>
      <div
        style={{
          fontFamily: DISPLAY,
          fontVariationSettings: "'opsz' 96",
          fontWeight: 800,
          fontSize: 470,
          letterSpacing: "-0.045em",
          lineHeight: 1,
          fontVariantNumeric: "tabular-nums",
          backgroundImage: tint ? `linear-gradient(${tint}, ${tint}), ${mosaic}` : mosaic,
          backgroundBlendMode: tint ? "multiply" : undefined,
          backgroundSize: tint ? "100% 100%, 1300px auto" : "1300px auto",
          backgroundPosition: tint ? `0 0, ${-(frame - at) * 0.8}px ${-(frame - at) * 3.2}px` : `${-(frame - at) * 0.8}px ${-(frame - at) * 3.2}px`,
          WebkitBackgroundClip: "text",
          backgroundClip: "text",
          color: "transparent",
          WebkitTextStroke: `3px ${stroke}`,
          marginTop: -40,
        }}
      >
        {count.toLocaleString("en-GB")}
      </div>
      <div style={{ marginTop: 18 }}>
        <Words words={words} out={out - 4} style={label(54, C.label, 600)} gap={0.28} />
      </div>
    </AbsoluteFill>
  );
};

export const Wall: React.FC = () => {
  const frame = useCurrentFrame();
  const cam = track(frame, [
    { f: F(6), z: -1100, rx: 58, rz: -20, s: 1 },
    { f: F(8.5), z: 0, rx: 34, rz: -14, s: 1, e: expoOut },
    { f: F(14.75), z: 120, rx: 30, rz: -10, s: 1.06 },
    { f: F(16), z: 900, rx: 8, rz: -2, s: 1.6, e: easeIn },
  ]);
  return (
    <AbsoluteFill>
      <Stage perspective={1500}>
        <div style={{ position: "absolute", left: 0, top: 0, transformStyle: "preserve-3d", transform: transformOf({ x: 960, y: 560, z: cam.z, rx: cam.rx, rz: cam.rz, s: cam.s * 1.18 }) }}>
          {Array.from({ length: COLS }, (_, col) => (
            <Column key={col} col={col} frame={frame} />
          ))}
        </div>
      </Stage>
      <AbsoluteFill style={{ background: C.canvas, opacity: 0.86 * ramp(frame, F(8.5), F(9.25), expoOut) * (1 - ramp(frame, CANDIDATES.out, CANDIDATES.out + 12, easeIn)) }} />
      <FillNumber
        frame={frame}
        at={CANDIDATES.at}
        out={CANDIDATES.out}
        from={4000}
        to={5405}
        behind
        tint="rgba(14,110,107,0.82)"
        stroke="#094F4C"
        label={[{ text: "candidates in ten Czech cities", at: F(12.6) }]}
      />
      <FillNumber
        frame={frame}
        at={POSTS.at}
        out={POSTS.out}
        from={10000}
        to={12595}
        stroke={C.label}
        label={[
          { text: "public posts from", at: F(9.25) },
          { text: "candidates’ own accounts", at: F(9.6) },
        ]}
      />
    </AbsoluteFill>
  );
};
