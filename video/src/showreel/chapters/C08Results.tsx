import { AbsoluteFill, useCurrentFrame } from "remotion";
import { CHAPTERS } from "../timing";
import { easeIn, easeOut, ramp } from "../theme";
import { Callout } from "../parts/Callout";
import { edges, place, Window } from "../parts/Window";
import { playhead, shot } from "../parts/Take";

// Capture "results": By the numbers, scrolled from the snapshot totals (0) past the official 2026
// results (about capture frame 130) to every list in Prague (2150 px).
const LAST = 209;
const PLAY = 50;
const LENGTH = CHAPTERS[7].to - CHAPTERS[7].from;

export const C08Results: React.FC = () => {
  const frame = useCurrentFrame();
  const enter = ramp(frame, 0, 14, easeOut);
  const exit = ramp(frame, LENGTH - 10, LENGTH, easeIn);
  const index = playhead(frame, PLAY, 0, LAST);
  const cam = { s: 0.94, dx: -130 + 900 * (1 - enter) - 900 * exit, dy: 0 };
  const e = edges(cam);
  const y = (v: number) => place(0, v, cam).y;
  const x = (v: number) => place(v, 0, cam).x;
  const end = PLAY + LAST;
  return (
    <AbsoluteFill style={{ opacity: Math.min(enter, 1 - exit * 0.5) }}>
      <Window src={shot("results", index)} cam={cam} />
      <Callout side="right" edge={e.right} from={y(96)} to={y(555)} text="What the snapshot holds, by platform, city and list" frame={frame} at={12} until={PLAY + 10} />
      <Callout side="right" edge={e.right} from={y(60)} to={y(860)} text="Official 2026 results · Czech Statistical Office, final count" frame={frame} at={PLAY + 112} until={end - 4} />
      <Callout side="right" edge={e.right} from={y(290)} to={y(900)} text="Votes and seats for every list, and every candidate inside it" frame={frame} at={end + 4} />
      <Callout side="bottom" edge={e.bottom} from={x(145)} to={x(1455)} text="5,405 candidacies · 127 lists · 464 seats" frame={frame} at={end + 22} reach={28} accent />
    </AbsoluteFill>
  );
};
