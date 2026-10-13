import { AbsoluteFill, Audio, Sequence, staticFile, useCurrentFrame } from "remotion";
import { Background, Grain } from "./parts/Background";
import { BlurDefs } from "./parts/Blur";
import { Hud } from "./parts/Hud";
import { beatFrame, chapterAt, CHAPTERS } from "./timing";
import { easeInOut, ramp } from "./theme";
import { C01Tagline } from "./chapters/C01Tagline";
import { C02Snapshot } from "./chapters/C02Snapshot";
import { C03Pipeline } from "./chapters/C03Pipeline";
import { C04Atlas } from "./chapters/C04Atlas";
import { C05Spotlight } from "./chapters/C05Spotlight";
import { C06Pulse } from "./chapters/C06Pulse";
import { C07Radar } from "./chapters/C07Radar";
import { C08Results } from "./chapters/C08Results";
import { C09Hackathon } from "./chapters/C09Hackathon";
import { C10Montage } from "./chapters/C10Montage";
import { C11EndCard } from "./chapters/C11EndCard";
import cues from "./cues.json";

const VIEWS = [C01Tagline, C02Snapshot, C03Pipeline, C04Atlas, C05Spotlight, C06Pulse, C07Radar, C08Results, C09Hackathon, C10Montage, C11EndCard];
// Where each chapter's ambient teal glow sits (fractions of the frame).
const GLOW = [
  [0.5, 0.46],
  [0.36, 0.42],
  [0.5, 0.5],
  [0.45, 0.5],
  [0.45, 0.5],
  [0.45, 0.5],
  [0.45, 0.5],
  [0.45, 0.5],
  [0.5, 0.36],
  [0.5, 0.48],
  [0.5, 0.42],
];

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
  const chapter = chapterAt(frame);
  const i = chapter.index - 1;
  const blend = ramp(frame, chapter.from, chapter.from + 14, easeInOut);
  const prev = GLOW[Math.max(0, i - 1)];
  const glowX = prev[0] + (GLOW[i][0] - prev[0]) * blend;
  const glowY = prev[1] + (GLOW[i][1] - prev[1]) * blend;
  return (
    <AbsoluteFill style={{ backgroundColor: "#040B0B" }}>
      <BlurDefs />
      <Background glowX={glowX} glowY={glowY} />
      {CHAPTERS.map((c, index) => {
        const View = VIEWS[index];
        return (
          <Sequence key={c.index} from={c.from} durationInFrames={c.to - c.from} layout="none">
            <AbsoluteFill>
              <View />
            </AbsoluteFill>
          </Sequence>
        );
      })}
      <Hud quiet={ramp(frame, beatFrame(88) + 4, beatFrame(88) + 22, easeInOut)} />
      <Grain />
      {audio ? <Soundtrack /> : null}
    </AbsoluteFill>
  );
};
