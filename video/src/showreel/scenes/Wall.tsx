import { AbsoluteFill, Img, useCurrentFrame } from "remotion";
import { vBlur } from "../parts/Blur";
import { Odometer, Words } from "../parts/Kinetic";
import { Card, Stage, transformOf } from "../parts/Stage";
import { track } from "../parts/track";
import { asset, C, clamp01, display, easeIn, easeInOut, expoOut, label, pop, ramp } from "../theme";
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

const FlipCard: React.FC<{ frame: number }> = ({ frame }) => {
  const rise = pop(frame, F(8), 0.9, 1.2);
  const p = track(frame, [
    { f: F(8), y: 1500, rx: 30 },
    { f: F(8) + 40, y: 560, rx: 0, e: expoOut },
    { f: F(14.4), y: 560, rx: 0 },
    { f: F(15.2), y: -900, rx: -50, e: easeIn },
  ]);
  const y = frame < F(8) + 40 ? 1500 + (560 - 1500) * rise : p.y;
  const flip = 180 * ramp(frame, F(12), F(12) + 22, easeInOut);
  const dip = 1 - 0.08 * Math.sin((flip / 180) * Math.PI);
  return (
    <div style={{ position: "absolute", left: 0, top: 0, transformStyle: "preserve-3d", transform: transformOf({ x: 960, y, rx: p.rx, ry: flip, s: dip }) }}>
      <Card pose={{ x: 0, y: 0 }} w={1140} h={520}>
        <div style={{ position: "absolute", left: 84, top: 70 }}>
          <Odometer value="12,595" from={F(8) + 4} dur={46} style={display(250)} />
        </div>
        <div style={{ position: "absolute", left: 90, top: 352 }}>
          <Words words={[{ text: "public posts from", at: F(9) }, { text: "candidates’ own accounts", at: F(9.5) }]} style={label(46)} gap={0.28} />
        </div>
      </Card>
      <Card pose={{ x: 0, y: 0, ry: 180 }} w={1140} h={520}>
        <div style={{ position: "absolute", left: 84, top: 70 }}>
          <Odometer value="5,405" from={F(12.3)} dur={34} style={display(250, C.brand)} />
        </div>
        <div style={{ position: "absolute", left: 90, top: 352 }}>
          <Words words={[{ text: "candidates in ten Czech cities", at: F(12.9) }]} style={label(46)} />
        </div>
      </Card>
    </div>
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
      <Stage perspective={1800}>
        <FlipCard frame={frame} />
      </Stage>
    </AbsoluteFill>
  );
};
