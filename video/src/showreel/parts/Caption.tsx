import { useCurrentFrame } from "remotion";
import { C, ramp, TEXT } from "../theme";
import { beatFrame } from "../timing";
import { VIEW } from "./Sheet";

export type Line = { beat: number; until: number; text: string };

// One caption at a time, in a fixed place under the sheet: sentence case, plain fades.
export const Captions: React.FC<{ lines: Line[] }> = ({ lines }) => {
  const frame = useCurrentFrame();
  const line = lines.find((l) => frame >= beatFrame(l.beat) && frame < beatFrame(l.until));
  if (!line) return null;
  const from = beatFrame(line.beat);
  const to = beatFrame(line.until);
  const opacity = Math.min(ramp(frame, from, from + 8), ramp(frame, to - 6, to, (t) => t, 1, 0));
  return (
    <div
      style={{
        position: "absolute",
        left: VIEW.x + 6,
        top: VIEW.y + VIEW.h + 36,
        fontFamily: TEXT,
        fontSize: 38,
        fontWeight: 560,
        letterSpacing: "-0.01em",
        color: C.label,
        opacity,
        whiteSpace: "nowrap",
      }}
    >
      {line.text}
    </div>
  );
};
