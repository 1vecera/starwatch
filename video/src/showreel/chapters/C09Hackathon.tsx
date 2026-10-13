import { AbsoluteFill, useCurrentFrame } from "remotion";
import { at, CHAPTERS } from "../timing";
import { C, display, easeIn, easeOut, label, LABEL, ramp, ring } from "../theme";
import { Mark } from "../parts/Mark";
import { hBlur } from "../parts/Blur";

// The result, as the hackathon published it (hq.agents007.ai/results).
const LENGTH = CHAPTERS[8].to - CHAPTERS[8].from;
const LINES = [
  { text: "Agents 0.0.7 hackathon · Prague · 8–9 October 2026", beat: 74.5, color: C.ink },
  { text: "Winner of the Social Media Deep Research topic", beat: 75.5, color: C.teal },
  { text: "38 projects · built solo in one night", beat: 76.5, color: LABEL },
];

export const C09Hackathon: React.FC = () => {
  const frame = useCurrentFrame();
  const form = ramp(frame, 0, 18, easeOut);
  const settle = ring((frame - 18) / 60, 2.4, 6);
  const title = ramp(frame, at(9, 73), at(9, 73) + 14, easeOut);
  const exit = ramp(frame, LENGTH - 12, LENGTH, easeIn);
  return (
    <AbsoluteFill style={{ transform: `translateX(${-1100 * exit}px)`, filter: exit > 0 ? hBlur(60 * exit * (1 - exit) * 4) : undefined }}>
      <div style={{ position: "absolute", left: 960 - 70, top: 230 }}>
        <Mark size={140} spread={1.6 * (1 - form)} rotate={-90 * (1 - form) + 6 * settle} glow={30 * form} style={{ opacity: form }} />
      </div>
      <div
        style={{
          ...display(168),
          position: "absolute",
          left: 0,
          right: 0,
          top: 420,
          textAlign: "center",
          opacity: title,
          transform: `scale(${1.12 - 0.12 * title})`,
          filter: title < 1 ? `blur(${(1 - title) * 12}px)` : undefined,
        }}
      >
        Overall champion
      </div>
      {LINES.map((l, i) => {
        const t = ramp(frame, at(9, l.beat), at(9, l.beat) + 10);
        return (
          <div key={i} style={{ ...label(24, l.color), position: "absolute", left: 0, right: 0, top: 640 + i * 46, textAlign: "center", opacity: t, transform: `translateY(${(1 - t) * 16}px)` }}>
            {l.text}
          </div>
        );
      })}
    </AbsoluteFill>
  );
};
