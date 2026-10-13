import { AbsoluteFill, Img, useCurrentFrame } from "remotion";
import { beatFrame, CHAPTERS } from "../timing";
import { C, display, label, LABEL, still } from "../theme";

// Two bars of cuts: four on the beat (the phone, real captures), then eight on eighth notes.
type Cut = { phone?: string; text?: string; sub?: string; teal?: boolean };
const CUTS: Cut[] = [
  { phone: "phone/welcome.png", sub: "The welcome screen on a phone" },
  { phone: "phone/atlas.png", sub: "The Star Atlas on a phone" },
  { text: "No sign-in", sub: "Open to everyone" },
  { text: "Open source", sub: "MIT · github.com/1vecera/starwatch", teal: true },
  { text: "A snapshot", sub: "8–9 October 2026, not live" },
  { text: "No polls", sub: "No forecasts, no scores", teal: true },
  { text: "Owners verified", sub: "By an independent public source" },
  { text: "Every post", sub: "Links back to its source", teal: true },
  { text: "5,405", sub: "Candidacies" },
  { text: "10 cities", sub: "City councils", teal: true },
  { text: "4 platforms", sub: "Instagram · Facebook · TikTok · X" },
  { text: "One night", sub: "Agents 0.0.7, Prague", teal: true },
];
const START = CHAPTERS[9].from;
const STARTS = [80, 81, 82, 83, 84, 84.5, 85, 85.5, 86, 86.5, 87, 87.5].map((b) => beatFrame(b) - START);

export const C10Montage: React.FC = () => {
  const frame = useCurrentFrame();
  let i = 0;
  STARTS.forEach((s, k) => {
    if (frame >= s) i = k;
  });
  const cut = CUTS[i];
  const since = frame - STARTS[i];
  const punch = Math.max(0, 1 - since / 6);
  return (
    <AbsoluteFill>
      {cut.phone ? (
        <>
          <div
            style={{
              position: "absolute",
              left: 960 - 195,
              top: 140,
              width: 390,
              height: 844,
              borderRadius: 44,
              overflow: "hidden",
              boxShadow: `0 0 0 10px #0E1616, 0 0 0 11px ${C.line}, 0 50px 140px rgba(0,0,0,0.7)`,
              transform: `scale(${1 + 0.03 * punch})`,
            }}
          >
            <Img src={still(cut.phone)} style={{ width: "100%", height: "100%" }} />
          </div>
          <div style={{ ...label(18, LABEL), position: "absolute", left: 960 + 260, top: 520 }}>{cut.sub}</div>
        </>
      ) : (
        <div style={{ position: "absolute", left: 0, right: 0, top: 360, textAlign: "center", transform: `scale(${1 + 0.05 * punch})` }}>
          <div style={{ ...display(176), color: cut.teal ? C.teal : C.ink }}>{cut.text}</div>
          <div style={{ ...label(26, C.ink2), marginTop: 34 }}>{cut.sub}</div>
        </div>
      )}
    </AbsoluteFill>
  );
};
