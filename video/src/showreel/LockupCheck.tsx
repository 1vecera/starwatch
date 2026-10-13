import { AbsoluteFill, Img, Sequence } from "remotion";
import { brand } from "./theme";
import { C11EndCard, LOCKUP, LOCKUP_AT, REST } from "./chapters/C11EndCard";

export type LockupCheckMode = "svg" | "chapter";

// Pixel check: the end card's resting lockup against the brand file itself, both on black.
export const LockupCheck: React.FC<{ mode: LockupCheckMode }> = ({ mode }) => (
  <AbsoluteFill style={{ backgroundColor: "#000" }}>
    {mode === "svg" ? (
      <Img src={brand("lockup-white.svg")} style={{ position: "absolute", left: LOCKUP_AT.x, top: LOCKUP_AT.y, width: LOCKUP.w, height: LOCKUP.h }} />
    ) : (
      <Sequence from={-(REST + 40)} layout="none">
        <AbsoluteFill style={{ clipPath: `inset(${LOCKUP_AT.y - 4}px 0 ${1080 - LOCKUP_AT.y - LOCKUP.h - 4}px 0)` }}>
          <C11EndCard />
        </AbsoluteFill>
      </Sequence>
    )}
  </AbsoluteFill>
);
