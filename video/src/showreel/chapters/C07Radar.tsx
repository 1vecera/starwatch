import { AbsoluteFill, useCurrentFrame } from "remotion";
import { CHAPTERS } from "../timing";
import { easeIn, easeOut, ramp } from "../theme";
import { Callout } from "../parts/Callout";
import { edges, place, Window } from "../parts/Window";
import { playhead, shot } from "../parts/Take";

// Capture "radar": the watchlist and the snapshot replay feed, scrolled 0 → 760 px.
const LAST = 149;
const PLAY = 40;
const LENGTH = CHAPTERS[6].to - CHAPTERS[6].from;

export const C07Radar: React.FC = () => {
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
      <Window src={shot("radar", index)} cam={cam} />
      <Callout side="bottom" edge={e.bottom} from={x(211)} to={x(531)} text="Watchlist with 2022 and 2026 results" frame={frame} at={14} reach={28} />
      <Callout side="right" edge={e.right} from={y(76)} to={y(557)} text="Snapshot replay: the 48 hours before collection" frame={frame} at={24} />
      <Callout side="top" edge={e.top} from={x(585)} to={x(1015)} text="Who posted what, and how it landed" frame={frame} at={PLAY + 30} reach={24} accent />
    </AbsoluteFill>
  );
};
