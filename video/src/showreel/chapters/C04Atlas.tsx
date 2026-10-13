import { AbsoluteFill, useCurrentFrame } from "remotion";
import { at, CHAPTERS } from "../timing";
import { easeIn, easeOut, label, LABEL, ramp } from "../theme";
import { Callout } from "../parts/Callout";
import { edges, place, Window } from "../parts/Window";
import { playhead, shot } from "../parts/Take";

// Capture "atlas": frames 0–109 fly from Czechia into Prague, frame 110 is Prague after selecting it
// (party islands drawn), frames 110–279 drift slowly over the city.
const FLIGHT = 110;
const LAST = 279;
const LENGTH = CHAPTERS[3].to - CHAPTERS[3].from;
const FLY = at(4, 26);
const ARRIVE = FLY + FLIGHT;

export const C04Atlas: React.FC = () => {
  const frame = useCurrentFrame();
  const reveal = ramp(frame, 0, 10, easeOut);
  const flash = 1 - ramp(frame, 0, 14, easeOut);
  const exit = ramp(frame, LENGTH - 10, LENGTH, easeIn);
  const index = frame < ARRIVE ? playhead(frame, FLY, 0, FLIGHT - 1) : playhead(frame, ARRIVE, FLIGHT, LAST);
  const dissolve = ramp(frame, ARRIVE, ARRIVE + 9);
  const cam = { s: 0.94 + 0.012 * ramp(frame, 0, FLY), dx: -130 - 900 * exit, dy: 0 };
  const e = edges(cam);
  const y = (cssY: number) => place(0, cssY, cam).y;
  const x = (cssX: number) => place(cssX, 0, cam).x;
  return (
    <AbsoluteFill style={{ opacity: 1 - exit * 0.5 }}>
      <Window
        src={shot("atlas", index)}
        under={frame >= ARRIVE && dissolve < 1 ? shot("atlas", FLIGHT - 1) : undefined}
        mix={dissolve}
        cam={cam}
        opacity={reveal}
      />
      <AbsoluteFill style={{ background: "#F2F7F7", opacity: flash * 0.9, mixBlendMode: "screen" }} />
      {/* Czechia: the overview panel and the ranked list of cities. */}
      <Callout side="right" edge={e.right} from={y(76)} to={y(290)} text="5,405 candidacies · 127 lists" frame={frame} at={12} until={FLY + 6} />
      <Callout side="right" edge={e.right} from={y(392)} to={y(784)} text="Ranked by reach: views where reported, otherwise likes + comments" frame={frame} at={22} until={FLY + 6} />
      {/* The flight: marker size is the chosen metric. */}
      <Callout side="bottom" edge={e.bottom} from={x(336)} to={x(720)} text="Marker size = reach · pick a city to fly in" frame={frame} at={FLY + 4} until={ARRIVE - 4} reach={28} />
      {/* Prague: the lists as islands of their posts, the city's top posts and its official result. */}
      <Callout side="bottom" edge={e.bottom} from={x(340)} to={x(1180)} text="Every list an island of its posts, sized by reach" frame={frame} at={ARRIVE + 10} reach={28} accent />
      <Callout side="right" edge={e.right} from={y(150)} to={y(330)} text="Top posts · each opens the original" frame={frame} at={ARRIVE + 26} />
      <Callout side="right" edge={e.right} from={y(818)} to={y(880)} text="2026 result · final count" frame={frame} at={ARRIVE + 44} />
      <div style={{ ...label(15, LABEL), position: "absolute", right: 94, top: 130, opacity: ramp(frame, 8, 16) * (1 - exit) }}>
        Real app · live site · scripted camera
      </div>
    </AbsoluteFill>
  );
};
