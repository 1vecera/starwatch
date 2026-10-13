import { AbsoluteFill, useCurrentFrame } from "remotion";
import { beatAt, chapterAt, CHAPTERS, DURATION, FPS } from "../timing";
import { C, easeOut, LABEL, label, ramp } from "../theme";
import { scramble } from "./Scramble";

const pad = (n: number) => String(n).padStart(2, "0");
const INSET = 56;
const ARM = 22;

const Bracket: React.FC<{ corner: "tl" | "tr" | "bl" | "br"; offset: number; opacity: number }> = ({ corner, offset, opacity }) => {
  const top = corner[0] === "t";
  const left = corner[1] === "l";
  return (
    <div
      style={{
        position: "absolute",
        width: ARM,
        height: ARM,
        opacity,
        [top ? "top" : "bottom"]: INSET - offset,
        [left ? "left" : "right"]: INSET - offset,
        borderColor: C.ink2,
        borderStyle: "solid",
        borderWidth: 0,
        [top ? "borderTopWidth" : "borderBottomWidth"]: 1.5,
        [left ? "borderLeftWidth" : "borderRightWidth"]: 1.5,
      }}
    />
  );
};

// The frame around the reel: title, timecode, beat lights, chapter, progress and the address.
// `quiet` fades the text and leaves the brackets.
export const Hud: React.FC<{ quiet?: number }> = ({ quiet = 0 }) => {
  const frame = useCurrentFrame();
  const boot = ramp(frame, 0, 22, easeOut);
  const chapter = chapterAt(frame);
  const since = frame - chapter.from;
  const name = scramble(chapter.name, ramp(since, 0, 6), `hud-${chapter.index}`, frame);
  const beat = Math.floor(beatAt(frame));
  const beatInBar = ((beat % 4) + 4) % 4;
  const secs = Math.floor(frame / FPS);
  const timecode = `00:00:${pad(secs)}:${pad(frame % FPS)}`;
  const progress = Math.min(1, frame / (DURATION - 1));
  const fade = ramp(frame, DURATION - 24, DURATION - 2, easeOut, 1, 0);
  const text = 1 - quiet;
  const type = (value: string, delay: number) => scramble(value, ramp(frame, delay, delay + 12), value, frame);

  return (
    <AbsoluteFill style={{ opacity: fade, pointerEvents: "none" }}>
      {(["tl", "tr", "bl", "br"] as const).map((corner) => (
        <Bracket key={corner} corner={corner} offset={(1 - boot) * 18} opacity={boot} />
      ))}
      <div style={{ position: "absolute", left: 94, top: 62, opacity: text }}>
        <div style={label(16, C.ink)}>{type("SHOWREEL '26", 2)}</div>
        <div style={{ ...label(16, LABEL), marginTop: 9 }}>{type("PRODUCT TOUR — STARWATCH", 6)}</div>
        <div style={{ display: "flex", gap: 6, marginTop: 12, opacity: boot }}>
          {[0, 1, 2, 3].map((i) => (
            <div
              key={i}
              style={{
                width: 8,
                height: 8,
                transform: "rotate(45deg)",
                background: i === beatInBar && frame > 0 ? C.teal : C.ink4,
                boxShadow: i === beatInBar ? `0 0 10px ${C.tealGlow}` : "none",
              }}
            />
          ))}
        </div>
      </div>
      <div style={{ position: "absolute", right: 94, top: 62, textAlign: "right", opacity: text }}>
        <div style={{ ...label(16, C.ink), letterSpacing: "0.12em", opacity: boot, fontVariantNumeric: "tabular-nums" }}>{timecode}</div>
        <div style={{ ...label(16, LABEL), marginTop: 9 }}>{type("1920×1080 · 60 FPS · 128 BPM", 8)}</div>
      </div>
      <div style={{ position: "absolute", left: 94, bottom: 70, opacity: text }}>
        <div style={{ ...label(16, LABEL), opacity: boot }}>/ {pad(CHAPTERS.length)}</div>
        <div style={{ ...label(16, C.ink), marginTop: 9, opacity: boot }}>
          <span style={{ color: C.teal }}>{pad(chapter.index)}</span>
          <span style={{ marginLeft: 14 }}>{name}</span>
        </div>
      </div>
      <div style={{ position: "absolute", right: 94, bottom: 70, textAlign: "right", opacity: text }}>
        <div style={{ width: 220, height: 1, background: C.ink4, marginLeft: "auto", position: "relative", opacity: boot }}>
          <div style={{ position: "absolute", left: 0, top: -0.5, height: 2, width: 220 * progress, background: C.teal, boxShadow: `0 0 8px ${C.tealGlow}` }} />
        </div>
        <div style={{ ...label(16, C.ink), marginTop: 16 }}>{type("STARWATCH.DANIELVECERA.COM", 10)}</div>
      </div>
    </AbsoluteFill>
  );
};
