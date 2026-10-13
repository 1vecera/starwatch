import { AbsoluteFill, useCurrentFrame } from "remotion";
import { at } from "../timing";
import { C, display, easeIn, easeOut, label, LABEL, ramp, ring } from "../theme";
import { Mark } from "../parts/Mark";

// The tagline from the app's welcome screen, one word per half beat, with the mark as the full stop.
const LINES = [
  { words: ["Who’s", "being", "heard"], beat: 1, color: C.ink },
  { words: ["Not", "just", "who’s", "talking"], beat: 4, color: C.teal },
];
const SIZE = 132;
const END = at(1, 8);

const Word: React.FC<{ text: string; frame: number; start: number; color: string }> = ({ text, frame, start, color }) => {
  const t = ramp(frame, start, start + 12);
  const blur = (1 - ramp(frame, start, start + 8)) * 14;
  return (
    <span
      style={{
        display: "inline-block",
        marginRight: SIZE * 0.24,
        opacity: t,
        transform: `translateY(${(1 - t) * 46}px)`,
        filter: blur > 0.3 ? `blur(${blur}px)` : undefined,
        color,
      }}
    >
      {text}
    </span>
  );
};

export const C01Tagline: React.FC = () => {
  const frame = useCurrentFrame();
  // The mark opens the reel as a glint, then waits at the end of each line as its full stop.
  const glint = ramp(frame, 0, 14) + 0.25 * ring((frame - 1) / 60, 2.2, 6);
  const toLine = ramp(frame, at(1, 0.6), at(1, 1), easeIn);
  const collapse = ramp(frame, END - 14, END, easeIn);
  const out = 1 - collapse;
  return (
    <AbsoluteFill>
      <AbsoluteFill style={{ opacity: 1 - toLine }}>
        <div style={{ position: "absolute", left: 960 - 60, top: 470 - 60 }}>
          <Mark size={120} rotate={45 * (1 - glint)} glow={24 * glint} style={{ transform: `scale(${0.3 + 0.7 * glint}) rotate(${45 * (1 - glint)}deg)` }} />
        </div>
        <div style={{ ...label(16, LABEL), position: "absolute", left: 0, right: 0, top: 580, textAlign: "center", opacity: ramp(frame, 6, 16) * (1 - toLine) }}>
          2026 Czech municipal elections · ten cities
        </div>
      </AbsoluteFill>
      <AbsoluteFill style={{ transform: `scale(${1 - 0.06 * collapse})`, opacity: out, filter: collapse > 0.05 ? `blur(${collapse * 10}px)` : undefined }}>
        {LINES.map((line, li) => {
          const top = li === 0 ? 372 : 520;
          const last = line.beat * 1 + (line.words.length - 1) * 0.5;
          const markIn = ramp(frame, at(1, last + 0.5), at(1, last + 0.5) + 12);
          return (
            <div key={li} style={{ ...display(SIZE), position: "absolute", left: 0, right: 0, top, textAlign: "center" }}>
              {line.words.map((w, wi) => (
                <Word key={wi} text={w} frame={frame} start={at(1, line.beat + wi * 0.5)} color={line.color} />
              ))}
              <span style={{ display: "inline-block", width: SIZE * 0.42, height: SIZE * 0.42, marginLeft: -SIZE * 0.16, verticalAlign: "baseline", position: "relative", top: 4 }}>
                <Mark size={SIZE * 0.42} color={C.teal} glow={8 * markIn} style={{ opacity: markIn, transform: `scale(${0.4 + 0.6 * markIn}) rotate(${90 * (1 - markIn)}deg)` }} />
              </span>
            </div>
          );
        })}
      </AbsoluteFill>
      <div style={{ ...label(16, LABEL), position: "absolute", left: 0, right: 0, top: 720, textAlign: "center", opacity: ramp(frame, at(1, 6), at(1, 6) + 10, easeOut) * out }}>
        Public posts of candidates, next to the official results
      </div>
    </AbsoluteFill>
  );
};
