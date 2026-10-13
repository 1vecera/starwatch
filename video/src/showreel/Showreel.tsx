import { AbsoluteFill, Audio, Img, interpolate, Sequence, staticFile, useCurrentFrame } from "remotion";
import { Canvas } from "./parts/Canvas";
import { Cam, Sheet, VIEW } from "./parts/Sheet";
import { Captions, Line } from "./parts/Caption";
import { shot } from "./parts/Take";
import { asset, C, easeInOut, easeOut, ramp, TEXT, WORDMARK } from "./theme";
import { beatFrame, DURATION } from "./timing";
import cues from "./cues.json";

// A camera keyframe: at `beat`, scale `m` (1 = the sheet's width) centred on CSS point (cx, cy).
type Key = { beat: number } & Cam;
type Shot = { from: number; to: number; take: string; index?: (frame: number) => number; keys: Key[] };

const rel = (frame: number, beat: number) => frame - beatFrame(beat);
const hold = (index: number) => () => index;

// Every shot is a real capture of starwatch.danielvecera.com (capture/capture.mjs). Coordinates are
// CSS pixels of the 1600×900 page, read off the captures.
const SHOTS: Shot[] = [
  // The welcome screen: the wall of campaign posts, easing toward the tagline card.
  { from: 0, to: 8, take: "welcome", keys: [{ beat: 0, m: 1, cx: 800, cy: 450 }, { beat: 8, m: 1.34, cx: 390, cy: 345 }] },
  // Star Atlas over Czechia, drifting toward Prague's marker.
  { from: 8, to: 24, take: "atlas", index: hold(0), keys: [{ beat: 8, m: 1, cx: 800, cy: 470 }, { beat: 24, m: 1.16, cx: 690, cy: 440 }] },
  // The drop: the real camera flight into Prague (110 captured frames, one per reel frame).
  { from: 24, to: 28, take: "atlas", index: (f) => Math.min(109, rel(f, 24)), keys: [{ beat: 24, m: 1.16, cx: 690, cy: 440 }, { beat: 26, m: 1, cx: 800, cy: 450 }] },
  // Prague's lists as islands of their posts, then in to SPOLU pro Prahu's island.
  {
    from: 28,
    to: 36,
    take: "atlas",
    index: (f) => 110 + Math.min(169, Math.max(0, rel(f, 28))),
    keys: [
      { beat: 28, m: 1, cx: 800, cy: 450 },
      { beat: 31, m: 1, cx: 800, cy: 450 },
      { beat: 33.5, m: 1.38, cx: 520, cy: 470 },
      { beat: 36, m: 1.42, cx: 515, cy: 470 },
    ],
  },
  // Its most-watched candidate: his views, then his 2026 result.
  {
    from: 36,
    to: 44,
    take: "kastovsky",
    keys: [
      { beat: 36, m: 1.12, cx: 780, cy: 470 },
      { beat: 39.5, m: 1.3, cx: 760, cy: 470 },
      { beat: 40.5, m: 1.45, cx: 965, cy: 300 },
      { beat: 44, m: 1.48, cx: 965, cy: 300 },
    ],
  },
  // The candidate with the most votes in Prague: his views, then his 2026 result.
  {
    from: 44,
    to: 52,
    take: "hlavacek",
    keys: [
      { beat: 44, m: 1.12, cx: 780, cy: 560 },
      { beat: 47.5, m: 1.3, cx: 760, cy: 560 },
      { beat: 48.5, m: 1.45, cx: 965, cy: 330 },
      { beat: 52, m: 1.48, cx: 965, cy: 330 },
    ],
  },
  // Pulse with the two side by side: the chart, then down to attention next to votes.
  {
    from: 52,
    to: 60,
    take: "versus",
    index: (f) => Math.min(89, Math.max(0, Math.round((rel(f, 54) * 90) / (beatFrame(56) - beatFrame(54))))),
    keys: [
      { beat: 52, m: 1, cx: 800, cy: 450 },
      { beat: 56, m: 1, cx: 800, cy: 450 },
      { beat: 57.5, m: 1.15, cx: 800, cy: 478 },
      { beat: 60, m: 1.18, cx: 800, cy: 478 },
    ],
  },
  // By the numbers: the official results per city, then every list in Prague.
  {
    from: 60,
    to: 68,
    take: "results",
    index: (f) => (rel(f, 64) < 0 ? 122 : Math.min(209, 122 + Math.round(rel(f, 64) * 2.4))),
    keys: [
      { beat: 60, m: 1, cx: 800, cy: 360 },
      { beat: 63.5, m: 1.08, cx: 800, cy: 350 },
      { beat: 64, m: 1, cx: 800, cy: 450 },
      { beat: 68, m: 1.06, cx: 800, cy: 470 },
    ],
  },
  // Look up your city: the Atlas again, in on the list of the ten cities.
  { from: 76, to: 88, take: "atlas", index: hold(0), keys: [{ beat: 76, m: 1, cx: 800, cy: 470 }, { beat: 80, m: 1.45, cx: 560, cy: 600 }, { beat: 88, m: 1.5, cx: 552, cy: 610 }] },
];

const LINES: Line[] = [
  { beat: 0.5, until: 8, text: "Candidates’ public posts in ten Czech cities, before the 2026 vote." },
  { beat: 8, until: 16, text: "Each city sized by the attention its candidates got." },
  { beat: 16, until: 24, text: "Collected 8–9 October 2026. A snapshot, not live." },
  { beat: 24, until: 28, text: "Fly into a city." },
  { beat: 28, until: 32, text: "Each list becomes an island of its posts." },
  { beat: 32, until: 36, text: "Most reach in Prague: SPOLU pro Prahu, 26M." },
  { beat: 36, until: 40, text: "Tomáš Kaštovský: 25M video views since 2023." },
  { beat: 40, until: 44, text: "85,284 votes. Elected, 11th by votes on his list." },
  { beat: 44, until: 48, text: "Petr Hlaváček: 999k video views since 2023." },
  { beat: 48, until: 52, text: "100,907 votes, the most in Prague." },
  { beat: 52, until: 56, text: "Pulse puts them side by side." },
  { beat: 56, until: 60, text: "Attention and votes: separate measures, never one score." },
  { beat: 60, until: 64, text: "Official 2026 results, final count." },
  { beat: 64, until: 68, text: "All 5,405 candidates, next to what they posted." },
  { beat: 68, until: 72, text: "Open to everyone. No sign-in." },
  { beat: 76, until: 82, text: "Look up your city at starwatch.danielvecera.com." },
  { beat: 82, until: 88, text: "Open source under MIT on GitHub." },
];

// Ease between camera keys.
const camAt = (keys: Key[], frame: number): Cam => {
  const t = (k: Key) => beatFrame(k.beat);
  if (frame <= t(keys[0])) return keys[0];
  for (let i = 0; i < keys.length - 1; i++) {
    const a = keys[i];
    const b = keys[i + 1];
    if (frame <= t(b)) {
      const p = interpolate(frame, [t(a), t(b)], [0, 1], { easing: easeInOut, extrapolateLeft: "clamp", extrapolateRight: "clamp" });
      return { m: a.m + (b.m - a.m) * p, cx: a.cx + (b.cx - a.cx) * p, cy: a.cy + (b.cy - a.cy) * p };
    }
  }
  return keys[keys.length - 1];
};

const ShotView: React.FC = () => {
  const frame = useCurrentFrame();
  const s = SHOTS.find((x) => frame >= beatFrame(x.from) && frame < beatFrame(x.to));
  if (!s) return null;
  const index = s.index ? s.index(frame) : 0;
  const cam = camAt(s.keys, frame);
  // Flight to islands: a nine-frame dissolve between the last flight frame and Prague after selection.
  const arrive = beatFrame(28);
  const dissolve = s.from === 28 ? ramp(frame, arrive, arrive + 9) : 1;
  return <Sheet src={shot(s.take, index)} under={s.from === 28 && dissolve < 1 ? shot("atlas", 109) : undefined} mix={dissolve} cam={cam} />;
};

// Open to everyone: the welcome screen on a phone (390×844 at 3×), a real capture.
const Phone: React.FC = () => {
  const frame = useCurrentFrame();
  const push = ramp(frame, beatFrame(68), beatFrame(72), easeInOut);
  const h = 800;
  const w = (h * 390) / 844;
  return (
    <div
      style={{
        position: "absolute",
        left: 960 - w / 2,
        top: VIEW.y + (VIEW.h - h) / 2,
        width: w,
        height: h,
        borderRadius: 46,
        overflow: "hidden",
        boxShadow: `0 0 0 1px ${C.hairline}, 0 0 0 9px ${C.surface}, 0 0 0 10px ${C.hairline}, 0 2px 4px rgb(15 23 42 / .05), 0 32px 64px -16px rgb(15 23 42 / .22)`,
        transform: `scale(${1 + 0.025 * push})`,
      }}
    >
      <Img src={asset("phone/welcome.png")} style={{ width: "100%", height: "100%" }} />
    </div>
  );
};

// The hackathon, said once and plainly.
const Hackathon: React.FC = () => {
  const frame = useCurrentFrame();
  const a = ramp(frame, beatFrame(72), beatFrame(72) + 10);
  const b = ramp(frame, beatFrame(73), beatFrame(73) + 10);
  return (
    <div style={{ position: "absolute", left: 0, right: 0, top: 410, textAlign: "center", fontFamily: TEXT }}>
      <div style={{ fontSize: 54, fontWeight: 620, letterSpacing: "-0.02em", color: C.label, opacity: a }}>Built at the Agents 0.0.7 hackathon in Prague.</div>
      <div style={{ fontSize: 34, fontWeight: 500, color: C.label2, marginTop: 22, opacity: b }}>Overall winner among 38 projects, 8–9 October 2026.</div>
    </div>
  );
};

// End card on the final hit: the lockup as the brand file itself (checked by StarwatchLockupCheck).
export const LOCKUP = { w: 260.9 * 3, h: 66 * 3 };
export const LOCKUP_AT = { x: Math.round(960 - (260.9 * 3) / 2), y: 330 };
export const REST = 14;
export const EndCard: React.FC<{ start?: number }> = ({ start = beatFrame(88) }) => {
  const frame = useCurrentFrame() - start;
  const logo = ramp(frame, 0, REST, easeOut);
  const line = (d: number) => ramp(frame, d, d + 12);
  const fade = ramp(frame, DURATION - start - 22, DURATION - start - 2, (t) => t, 1, 0);
  return (
    <AbsoluteFill style={{ opacity: fade }}>
      <Img
        src={asset("brand/lockup.svg")}
        style={{ position: "absolute", left: LOCKUP_AT.x, top: LOCKUP_AT.y, width: LOCKUP.w, height: LOCKUP.h, opacity: logo, transform: frame < REST ? `translateY(${(1 - logo) * 18}px)` : undefined }}
      />
      <div style={{ position: "absolute", left: 0, right: 0, top: 600, textAlign: "center" }}>
        <div style={{ fontFamily: WORDMARK, fontWeight: 700, fontSize: 46, color: C.label, letterSpacing: "-0.01em", opacity: line(8) }}>starwatch.danielvecera.com</div>
        <div style={{ fontFamily: TEXT, fontSize: 28, color: C.label2, marginTop: 26, opacity: line(18) }}>Open source: github.com/1vecera/starwatch</div>
        <div style={{ fontFamily: TEXT, fontSize: 28, color: C.label3, marginTop: 10, opacity: line(26) }}>Made by Daniel Večeřa, Prague</div>
      </div>
    </AbsoluteFill>
  );
};

// Studio preview only; renders are muted and showreel/mix.py masters the same cue sheet.
const Soundtrack: React.FC = () => (
  <>
    <Audio src={staticFile(`showreel/audio/${cues.score.file}`)} volume={10 ** (cues.score.gain_db / 20)} />
    {cues.cues.map((cue, i) => {
      const peak = cues.sfx_peaks_s[cue.sfx as keyof typeof cues.sfx_peaks_s];
      return (
        <Sequence key={i} from={Math.round(cue.frame - peak * cues.fps)} layout="none">
          <Audio src={staticFile(`showreel/audio/${cue.sfx}.mp3`)} volume={10 ** (cue.gain_db / 20)} />
        </Sequence>
      );
    })}
  </>
);

export const StarwatchShowreel: React.FC<{ audio?: boolean }> = ({ audio = true }) => {
  const frame = useCurrentFrame();
  const sheet = SHOTS.some((x) => frame >= beatFrame(x.from) && frame < beatFrame(x.to));
  const disclose = ramp(frame, 10, 24) * (sheet ? 1 : 0);
  return (
    <AbsoluteFill>
      <Canvas />
      <ShotView />
      {frame >= beatFrame(68) && frame < beatFrame(72) ? <Phone /> : null}
      {frame >= beatFrame(72) && frame < beatFrame(76) ? <Hackathon /> : null}
      {frame >= beatFrame(88) ? <EndCard /> : null}
      <Captions lines={LINES} />
      <div
        style={{
          position: "absolute",
          right: 1920 - (VIEW.x + VIEW.w) + 6,
          top: VIEW.y + VIEW.h + 48,
          fontFamily: TEXT,
          fontSize: 20,
          color: C.label3,
          opacity: disclose,
        }}
      >
        Real captures of the live app
      </div>
      {audio ? <Soundtrack /> : null}
    </AbsoluteFill>
  );
};
