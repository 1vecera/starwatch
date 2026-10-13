import { Composition } from "remotion";
import { StarwatchShowreel } from "./showreel/Showreel";
import { LockupCheck, LockupCheckMode } from "./showreel/LockupCheck";
import { DURATION, FPS, HEIGHT, WIDTH } from "./showreel/timing";

export const Root: React.FC = () => (
  <>
    <Composition id="StarwatchShowreel" component={StarwatchShowreel} durationInFrames={DURATION} fps={FPS} width={WIDTH} height={HEIGHT} />
    <Composition
      id="StarwatchLockupCheck"
      component={LockupCheck}
      defaultProps={{ mode: "svg" as LockupCheckMode }}
      durationInFrames={1}
      fps={FPS}
      width={WIDTH}
      height={HEIGHT}
    />
  </>
);
