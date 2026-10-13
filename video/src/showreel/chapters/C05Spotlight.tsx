import { AbsoluteFill, useCurrentFrame } from "remotion";
import { CHAPTERS } from "../timing";
import { easeIn, easeOut, ramp } from "../theme";
import { Callout } from "../parts/Callout";
import { edges, place, Window } from "../parts/Window";
import { playhead, shot } from "../parts/Take";

// Capture "spotlight": Petr Hlaváček's page, scrolled from his profile (0) to his best posts (700 px).
const LAST = 149;
const PLAY = 52;
const LENGTH = CHAPTERS[4].to - CHAPTERS[4].from;

export const C05Spotlight: React.FC = () => {
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
      <Window src={shot("spotlight", index)} cam={cam} />
      <Callout side="right" edge={e.right} from={y(163)} to={y(712)} text="His official 2026 result next to the attention his posts got" frame={frame} at={14} until={PLAY + 8} />
      <Callout side="bottom" edge={e.bottom} from={x(80)} to={x(384)} text="Every candidate in the city" frame={frame} at={22} until={PLAY + 8} reach={28} />
      <Callout side="right" edge={e.right} from={y(170)} to={y(900)} text="Best posts with video playback · each opens the source" frame={frame} at={PLAY + 112} accent />
    </AbsoluteFill>
  );
};
