import { AbsoluteFill, useCurrentFrame } from "remotion";
import { CHAPTERS } from "../timing";
import { easeIn, easeOut, ramp } from "../theme";
import { Callout } from "../parts/Callout";
import { edges, place, Window } from "../parts/Window";
import { playhead, shot } from "../parts/Take";

// Capture "pulse": a candidate and three rivals; the chart (0), then the results table (1170 px).
const LAST = 149;
const PLAY = 62;
const LENGTH = CHAPTERS[5].to - CHAPTERS[5].from;

export const C06Pulse: React.FC = () => {
  const frame = useCurrentFrame();
  const enter = ramp(frame, 0, 14, easeOut);
  const exit = ramp(frame, LENGTH - 10, LENGTH, easeIn);
  const index = playhead(frame, PLAY, 0, LAST);
  const cam = { s: 0.94, dx: -130 + 900 * (1 - enter) - 900 * exit, dy: 0 };
  const e = edges(cam);
  const y = (v: number) => place(0, v, cam).y;
  const x = (v: number) => place(v, 0, cam).x;
  return (
    <AbsoluteFill style={{ opacity: Math.min(enter, 1 - exit * 0.5) }}>
      <Window src={shot("pulse", index)} cam={cam} />
      <Callout side="bottom" edge={e.bottom} from={x(92)} to={x(900)} text="Head to head · interactions by posting date" frame={frame} at={14} until={PLAY + 8} reach={28} />
      <Callout side="right" edge={e.right} from={y(283)} to={y(900)} text="Topic mix from reviewed labels" frame={frame} at={22} until={PLAY + 8} />
      <Callout side="right" edge={e.right} from={y(87)} to={y(670)} text="2022 votes, attention and the 2026 result: separate measures, never one score" frame={frame} at={PLAY + 118} accent />
    </AbsoluteFill>
  );
};
