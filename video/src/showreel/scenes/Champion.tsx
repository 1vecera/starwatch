import { AbsoluteFill, useCurrentFrame } from "remotion";
import { vBlur } from "../parts/Blur";
import { Words } from "../parts/Kinetic";
import { Mark } from "../parts/Mark";
import { display, easeIn, label, ramp } from "../theme";
import { beatFrame as F } from "../timing";

// The hackathon, in one bar: the only full-bleed teal in the film. It wipes in on a slant, says it once,
// and lifts away.
export const CHAMPION = { from: F(67.6), in: F(68) + 2, out: F(71.4), to: F(72) };

export const Champion: React.FC = () => {
  const frame = useCurrentFrame();
  // The slanted edge accelerates across and covers the frame on the beat; the words ride in behind it.
  const edge = 2300 - 2650 * ramp(frame, CHAMPION.from, CHAMPION.in, easeIn);
  const lift = (f: number) => -1100 * ramp(f, CHAMPION.out, CHAMPION.to, easeIn);
  const y = lift(frame);
  return (
    <AbsoluteFill
      style={{
        background: "#0E6E6B",
        clipPath: `polygon(${edge}px 0, 2400px 0, 2400px 1080px, ${edge - 320}px 1080px)`,
        transform: `translateY(${y}px)`,
        filter: vBlur(y - lift(frame - 1)),
      }}
    >
      <Mark cx={1560} cy={540} unit={15} color="rgba(255,255,255,0.09)" rotate={(frame - CHAMPION.from) * 0.6} />
      <div style={{ position: "absolute", left: 140, top: 368 }}>
        <Words words={[{ text: "Overall", at: F(68) }, { text: "champion", at: F(68.25) }]} style={display(168, "#FFFFFF")} />
      </div>
      <div style={{ position: "absolute", left: 148, top: 576 }}>
        <Words words={[{ text: "Agents 0.0.7 hackathon, Prague.", at: F(69) }, { text: "38 projects.", at: F(69.5) }]} style={label(50, "rgba(255,255,255,0.88)", 560)} gap={0.3} />
      </div>
    </AbsoluteFill>
  );
};
