import { AbsoluteFill, Img } from "remotion";
import { asset, C } from "./theme";
import { EndCard, LOCKUP, LOCKUP_AT, REST } from "./Showreel";

export type LockupCheckMode = "svg" | "chapter";

// Pixel check: the end card's resting lockup against the brand file itself, both on the canvas colour.
export const LockupCheck: React.FC<{ mode: LockupCheckMode }> = ({ mode }) => (
  <AbsoluteFill style={{ backgroundColor: C.canvas }}>
    {mode === "svg" ? (
      <Img src={asset("brand/lockup.svg")} style={{ position: "absolute", left: LOCKUP_AT.x, top: LOCKUP_AT.y, width: LOCKUP.w, height: LOCKUP.h }} />
    ) : (
      <AbsoluteFill style={{ clipPath: `inset(${LOCKUP_AT.y - 4}px 0 ${1080 - LOCKUP_AT.y - LOCKUP.h - 4}px 0)` }}>
        <EndCard start={-(REST + 30)} />
      </AbsoluteFill>
    )}
  </AbsoluteFill>
);
