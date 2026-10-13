import { AbsoluteFill, useCurrentFrame } from "remotion";
import { Highlight, Words } from "../parts/Kinetic";
import { Card, Stage } from "../parts/Stage";
import { kick, track } from "../parts/track";
import { asset, C, display, easeIn, expoOut } from "../theme";
import { beatFrame as F } from "../timing";

// Prague's marker on the first frame of the Atlas flight (take atlas-open, read from its take.json).
export const PRAHA = { x: 779, y: 517 };
const PERSPECTIVE = 1600;

// A hard cut into the Star Atlas close up; it pulls back to a tilted sheet under the question, swings
// up to face the camera, then pushes in while Prague grows into a teal disc that fills the frame on
// the drop. The flight opens out of that disc (Flight.tsx).
export const Czechia: React.FC = () => {
  const frame = useCurrentFrame();
  const p = track(frame, [
    { f: F(16), y: 540, z: 700, rx: 16, rz: -4, r: 20 },
    { f: F(17.5), y: 640, z: -120, rx: 28, rz: -5, r: 20, e: expoOut },
    { f: F(20.75), y: 625, z: -60, rx: 26, rz: -2, r: 20, e: (t: number) => t },
    { f: F(21.75), y: 540, z: 0, rx: 0, rz: 0, r: 0, e: expoOut },
    { f: F(23), y: 540, z: 260, rx: 0, rz: 0, r: 0, e: easeIn },
  ]);
  // Prague on screen while the flat sheet pushes toward the camera.
  const k = PERSPECTIVE / (PERSPECTIVE - (frame >= F(21.75) ? p.z : 0));
  const prague = { x: 960 + (PRAHA.x - 960) * k, y: 540 + (PRAHA.y - 540) * k };
  const grow = Math.min(1, Math.max(0, (frame - F(23)) / (F(24) - F(23))));
  const disc = frame >= F(23) ? 56 + 1400 * easeIn(grow) : 0;
  const rings = [F(22), F(22.5)].map((at) => kick(frame, at, 24));
  return (
    <AbsoluteFill>
      <Stage perspective={PERSPECTIVE}>
        <Card pose={{ x: 960, y: p.y, z: p.z, rx: p.rx, rz: p.rz }} w={1920} h={1080} src={asset("atlas-open/0000.png")} radius={p.r} shadow={frame < F(21.75)} filter="contrast(1.12) saturate(1.3)" />
      </Stage>
      <div style={{ position: "absolute", left: 130, top: 96 }}>
        <Words words={[{ text: "Who", at: F(16.5) }, { text: "got", at: F(16.75) }, { text: "the", at: F(17) }]} out={F(20.5)} style={display(132)} />
        <span style={{ display: "inline-block", width: "0.24em", fontSize: 132 }} />
        <Highlight at={F(18)} out={F(20.5)} color={C.brand} size={132}>
          {(ink) => <Words words={[{ text: "attention?", at: F(17.5) }]} out={F(20.5)} style={display(132, ink ? C.label : "#FFFFFF")} />}
        </Highlight>
      </div>
      <svg width={1920} height={1080} style={{ position: "absolute", inset: 0 }}>
        {frame >= F(21.75)
          ? rings.map((r, i) => (r > 0 ? <circle key={i} cx={prague.x} cy={prague.y} r={60 + 140 * (1 - r)} fill="none" stroke={C.brand} strokeWidth={3} strokeOpacity={0.85 * r} /> : null))
          : null}
        {disc > 0 ? <circle cx={prague.x} cy={prague.y} r={disc} fill={C.brand} /> : null}
      </svg>
    </AbsoluteFill>
  );
};
