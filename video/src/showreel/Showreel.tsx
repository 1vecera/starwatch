import { AbsoluteFill, Audio, Sequence, staticFile, useCurrentFrame } from "remotion";
import { BlurDefs } from "./parts/Blur";
import { Canvas } from "./parts/Canvas";
import { BladeSweep, sweepSwap } from "./parts/Mark";
import { kick } from "./parts/track";
import { Champion, CHAMPION } from "./scenes/Champion";
import { Cities, CTA_OUT } from "./scenes/Cities";
import { Czechia } from "./scenes/Czechia";
import { Duel } from "./scenes/Duel";
import { EndCard, MarkBuild } from "./scenes/Finale";
import { Flight, WHIP_AT } from "./scenes/Flight";
import { LOCK, Open, OpenMark } from "./scenes/Open";
import { Phone } from "./scenes/Phone";
import { Tools, TOOLS_TO } from "./scenes/Tools";
import { Wall } from "./scenes/Wall";
import { C, easeOut, ramp } from "./theme";
import { beatAt, beatFrame as F } from "./timing";
import cues from "./cues.json";

export { EndCard, LOCKUP, LOCKUP_AT, REST } from "./scenes/Finale";

// The teal blade covers the frame just before beat 56, so the reveal lands on the first tool.
const SWEEP = { at: F(56) - 16, dur: 26 };
const SWAP = sweepSwap(SWEEP.at, SWEEP.dur);

// Scene windows on absolute frames; neighbours overlap where one transitions into the next.
const SCENES: { from: number; to: number; View: React.FC }[] = [
  { from: 0, to: F(7.1), View: Open },
  { from: F(6), to: F(16), View: Wall },
  { from: 0, to: F(7.1), View: OpenMark },
  { from: F(16), to: F(24), View: Czechia },
  { from: F(24), to: WHIP_AT + 9, View: Flight },
  { from: WHIP_AT - 9, to: SWAP, View: Duel },
  { from: SWAP, to: TOOLS_TO + 4, View: Tools },
  { from: F(63.7), to: CHAMPION.in + 1, View: Phone },
  { from: CHAMPION.out, to: CTA_OUT + 16, View: Cities },
  { from: CHAMPION.from, to: CHAMPION.to, View: Champion },
  { from: F(83.4), to: F(88) + 6, View: MarkBuild },
];

// Hits that shake the whole frame a little: the drop, the head-to-head clash, the final hit.
const HITS = [F(24), F(48), F(88)];
const shake = (frame: number) => {
  const k = HITS.reduce((sum, at) => sum + kick(frame, at, 16), 0);
  return { k: Math.min(1, k), x: Math.sin(frame * 2.1) * 9 * k, y: Math.cos(frame * 2.7) * 7 * k };
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
  const b = beatAt(frame);
  // The contours: drawn on in the opening, lifted by the lock and, from the drop to the end card, by every kick.
  const phase = b - Math.floor(b);
  const groove = b >= 24 && b < 88 ? 0.55 * Math.exp(-6 * phase) : 0;
  const lift = Math.max(groove, kick(frame, LOCK, 30), kick(frame, F(88), 40));
  const s = shake(frame);
  const fullBleed = (frame >= F(21.75) && frame < WHIP_AT - 9) || (frame >= CHAMPION.in && frame < CHAMPION.out);
  return (
    <AbsoluteFill style={{ backgroundColor: C.canvas }}>
      <BlurDefs />
      <AbsoluteFill style={{ transform: `translate(${s.x}px, ${s.y}px) scale(${1 + 0.02 * s.k})` }}>
        {fullBleed ? null : <Canvas draw={ramp(frame, 0, F(5), easeOut)} lift={lift} zoom={1 + 0.0007 * frame} />}
        {SCENES.map(({ from, to, View }, i) => (frame >= from && frame < to ? <View key={i} /> : null))}
        {frame >= F(88) ? <EndCard /> : null}
        <BladeSweep at={SWEEP.at} dur={SWEEP.dur} />
      </AbsoluteFill>
      {audio ? <Soundtrack /> : null}
    </AbsoluteFill>
  );
};
