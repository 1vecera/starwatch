import { AbsoluteFill, Img, useCurrentFrame } from "remotion";
import { vBlur } from "../parts/Blur";
import { Words } from "../parts/Kinetic";
import { Stage, transformOf } from "../parts/Stage";
import { track } from "../parts/track";
import { asset, C, display, ELEV3, expoOut, pop } from "../theme";
import { beatFrame as F } from "../timing";

// Open to everyone: the welcome screen on a phone (390×844 at 3×, a real capture) drops in spinning and
// lands on the beat.
const H = 800;
const W = (H * 390) / 844;

export const Phone: React.FC = () => {
  const frame = useCurrentFrame();
  const land = F(64.25);
  const p = (f: number) =>
    track(f, [
      { f: F(63.7), y: -1400, rz: -28, ry: 50, rx: 10 },
      { f: land, y: 545, rz: -5, ry: -12, rx: 4, e: expoOut },
      { f: F(68), y: 545, rz: -3, ry: -4, rx: 2 },
    ]);
  const now = p(frame);
  const bounce = frame >= land ? 1 + 0.05 * (1 - pop(frame, land, 1.2, 0.8)) : 1;
  return (
    <AbsoluteFill>
      <Stage perspective={1600}>
        <div
          style={{
            position: "absolute",
            left: -W / 2,
            top: -H / 2,
            width: W,
            height: H,
            borderRadius: 46,
            overflow: "hidden",
            boxShadow: `0 0 0 1px ${C.hairline}, 0 0 0 9px ${C.surface}, 0 0 0 10px ${C.hairline}, ${ELEV3}`,
            transform: transformOf({ x: 560, y: now.y, rx: now.rx, ry: now.ry, rz: now.rz, s: bounce }),
            filter: vBlur(now.y - p(frame - 1).y),
          }}
        >
          <Img src={asset("phone/welcome.png")} style={{ width: "100%", height: "100%", display: "block" }} />
        </div>
      </Stage>
      <div style={{ position: "absolute", left: 900, top: 372 }}>
        <Words words={[{ text: "Open", at: F(64.5) }, { text: "to", at: F(64.75) }, { text: "everyone.", at: F(65) }]} out={F(67.4)} style={display(118)} />
      </div>
      <div style={{ position: "absolute", left: 900, top: 520 }}>
        <Words words={[{ text: "No", at: F(66) }, { text: "sign-in.", at: F(66.25) }]} out={F(67.4)} style={display(118, C.brand)} />
      </div>
    </AbsoluteFill>
  );
};
