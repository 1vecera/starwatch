import { AbsoluteFill, Img, useCurrentFrame } from "remotion";
import { at, CHAPTERS } from "../timing";
import { C, display, easeIn, easeOut, label, LABEL, ramp, still } from "../theme";

// What the snapshot holds, one figure per beat; the figures are the ones on the app's By the numbers page.
const STATS = [
  { value: 12595, text: "public posts", beat: 9 },
  { value: 110, text: "verified accounts", beat: 10 },
  { value: 10, text: "cities", beat: 11 },
  { value: 4, text: "platforms", beat: 12, note: "Instagram · Facebook · TikTok · X" },
];
const LENGTH = CHAPTERS[1].to - CHAPTERS[1].from;
const fmt = (n: number) => Math.round(n).toLocaleString("en-US");

export const C02Snapshot: React.FC = () => {
  const frame = useCurrentFrame();
  const enter = ramp(frame, 0, 16);
  const exit = ramp(frame, LENGTH - 10, LENGTH, easeIn);
  // The real welcome screen, framed on the right: the candidate wall the numbers describe.
  const shotIn = ramp(frame, at(2, 8.5), at(2, 9.5));
  return (
    <AbsoluteFill style={{ opacity: 1 - exit, transform: `translateY(${-60 * exit}px)` }}>
      <div
        style={{
          position: "absolute",
          left: 1040,
          top: 250,
          width: 720,
          height: 405,
          borderRadius: 12,
          overflow: "hidden",
          boxShadow: `0 0 0 1px ${C.line}, 0 40px 120px rgba(0,0,0,0.6)`,
          opacity: shotIn,
          transform: `perspective(1800px) rotateY(${-10 * (1 - shotIn) - 4}deg) translateX(${(1 - shotIn) * 80}px)`,
        }}
      >
        <Img src={still("welcome/0000.png")} style={{ width: "100%", height: "100%" }} />
      </div>
      <div style={{ ...label(14, LABEL), position: "absolute", left: 1040, top: 672, opacity: shotIn }}>
        The welcome screen · real capture
      </div>
      <div style={{ position: "absolute", left: 200, top: 200, opacity: enter }}>
        {STATS.map((s, i) => {
          const start = at(2, s.beat);
          const t = ramp(frame, start, start + 22, easeOut);
          const shown = ramp(frame, start - 2, start + 6);
          const big = i === 0;
          return (
            <div key={s.text} style={{ display: "flex", alignItems: "baseline", gap: 22, marginTop: i === 0 ? 0 : 18, opacity: shown, transform: `translateX(${(1 - shown) * -30}px)` }}>
              <div style={{ ...display(big ? 150 : 88), fontVariantNumeric: "tabular-nums", minWidth: big ? 0 : 150, textAlign: big ? "left" : "right", color: big ? C.ink : C.teal }}>
                {fmt(s.value * t)}
              </div>
              <div style={{ ...label(big ? 22 : 20, C.ink) }}>
                {s.text}
                {s.note ? <span style={{ color: LABEL, marginLeft: 16 }}>{s.note}</span> : null}
              </div>
            </div>
          );
        })}
      </div>
      <div style={{ ...label(18, C.teal), position: "absolute", left: 200, top: 760, opacity: ramp(frame, at(2, 13.5), at(2, 14)) }}>
        Collected 8–9 October 2026 · a snapshot, not live
      </div>
    </AbsoluteFill>
  );
};
