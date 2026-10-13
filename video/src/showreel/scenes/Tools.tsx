import { AbsoluteFill, Img, useCurrentFrame } from "remotion";
import { hBlur } from "../parts/Blur";
import { Words } from "../parts/Kinetic";
import { Card, Pose, Stage } from "../parts/Stage";
import { shot } from "../parts/Take";
import { kick, track } from "../parts/track";
import { asset, display, easeIn, expoOut } from "../theme";
import { beatFrame as F } from "../timing";

// Four of the app's tools in hard cuts, two beats each: the tool's own icon and name, and its real page
// scrolling on a sheet. The sheets alternate sides, each enters a different way and pushes the last one
// out, so the frame is never empty between cuts.
const TOOLS = [
  { name: ["Spotlight"], icon: "icon-spotlight.svg", take: "spotlight", frames: 150 },
  { name: ["Pulse"], icon: "icon-pulse.svg", take: "pulse", frames: 150 },
  { name: ["Radar"], icon: "icon-radar.svg", take: "radar", frames: 151 },
  { name: ["By the", "numbers"], icon: "icon-data.svg", take: "results", frames: 210 },
];
export const TOOLS_FROM = F(56);
export const TOOLS_TO = F(64);
const W = 1180;
const H = 664;

const rest = (side: 1 | -1): Pose => ({ x: side > 0 ? 1340 : 580, y: 540, z: 0, rx: 6, ry: -24 * side, rz: 0, s: 1 });
const enter = (i: number, side: 1 | -1): Pose => {
  const r = rest(side);
  return [{ ...r, x: 3300, ry: -40 }, { ...r, y: 1900, rx: 60 }, { ...r, ry: 120, x: 300 }, { ...r, z: -3200, rz: -20 }][i];
};
const exit = (side: 1 | -1): Pose => ({ ...rest(side), x: side > 0 ? 2900 : -900, ry: -40 * side, s: 0.9 });

const Sheet: React.FC<{ i: number; frame: number }> = ({ i, frame }) => {
  const tool = TOOLS[i];
  const side = i % 2 ? -1 : 1;
  const cut = F(56 + i * 2);
  const next = F(58 + i * 2);
  const pose = (f: number) =>
    track(f, [
      { f: cut - 6, ...enter(i, side) },
      { f: cut + 12, ...rest(side), e: expoOut },
      { f: next - 4, ...rest(side), ry: -18 * side, s: 1.04 },
      { f: next + 4, ...exit(side), e: easeIn },
    ]) as Pose;
  const p = pose(frame);
  const index = Math.min(tool.frames - 1, Math.max(0, Math.round((frame - cut) * 2.4)));
  return <Card pose={p} w={W} h={H} src={shot(tool.take, index)} filter={hBlur(p.x - pose(frame - 1).x)} />;
};

export const Tools: React.FC = () => {
  const frame = useCurrentFrame();
  return (
    <AbsoluteFill>
      <Stage perspective={1700}>
        {TOOLS.map((_, i) => {
          const cut = F(56 + i * 2);
          const next = F(58 + i * 2);
          return frame >= cut - 6 && frame < next + 4 ? <Sheet key={i} i={i} frame={frame} /> : null;
        })}
      </Stage>
      {TOOLS.map((tool, i) => {
        const cut = F(56 + i * 2);
        const leave = F(58 + i * 2) - 6;
        if (frame < cut - 2 || frame > leave + 12) return null;
        const right = i % 2 === 1;
        const pop = 1 + 0.25 * kick(frame, cut, 12);
        const at: React.CSSProperties = right ? { right: 150, textAlign: "right" } : { left: 150 };
        return (
          <div key={i}>
            <div style={{ position: "absolute", top: 320, ...at }}>
              <Img src={asset(`brand/${tool.icon}`)} style={{ width: 108, height: 108, transform: `scale(${frame >= cut && frame < leave + 4 ? pop : 0})`, transformOrigin: "50% 50%" }} />
            </div>
            {tool.name.map((line, k) => (
              <div key={k} style={{ position: "absolute", top: 466 + k * 136, ...at }}>
                <Words words={[{ text: line, at: cut + k * 3 }]} out={leave} style={display(140)} />
              </div>
            ))}
          </div>
        );
      })}
    </AbsoluteFill>
  );
};
