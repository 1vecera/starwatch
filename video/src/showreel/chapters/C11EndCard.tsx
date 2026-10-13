import { AbsoluteFill, Img, useCurrentFrame } from "remotion";
import { CHAPTERS } from "../timing";
import { brand, C, easeIn, easeOut, label, LABEL, ramp, ring, WORDMARK } from "../theme";
import { Mark } from "../parts/Mark";

// The final hit: the mark's shards slam together into the lockup, which then rests as the brand file
// itself (app/web/brand/lockup-white.svg at 3×), checked pixel for pixel by StarwatchLockupCheck.
export const LOCKUP = { w: 260.9 * 3, h: 66 * 3 };
export const LOCKUP_AT = { x: Math.round(960 - (260.9 * 3) / 2), y: 360 };
const MARK = { cx: LOCKUP_AT.x + 31 * 3, cy: LOCKUP_AT.y + 33 * 3, size: 64 * 0.9062 * 3 };
export const REST = 26;
const LENGTH = CHAPTERS[10].to - CHAPTERS[10].from;

export const C11EndCard: React.FC = () => {
  const frame = useCurrentFrame();
  const slam = ramp(frame, 0, 10, easeOut);
  const shake = ring(frame / 60, 9, 9) * 6;
  const wordmark = ramp(frame, 8, REST, easeOut);
  const atRest = frame >= REST;
  const flash = 1 - ramp(frame, 0, 16, easeOut);
  const lines = (delay: number) => ramp(frame, delay, delay + 12);
  const fade = ramp(frame, LENGTH - 26, LENGTH - 2, easeIn, 1, 0);
  return (
    <AbsoluteFill style={{ opacity: fade }}>
      <AbsoluteFill style={{ background: `radial-gradient(circle at 50% 42%, rgba(79,203,194,${0.35 * flash}), transparent 55%)` }} />
      {atRest ? (
        <Img src={brand("lockup-white.svg")} style={{ position: "absolute", left: LOCKUP_AT.x, top: LOCKUP_AT.y, width: LOCKUP.w, height: LOCKUP.h }} />
      ) : (
        <>
          <div style={{ position: "absolute", left: MARK.cx - MARK.size / 2 + shake, top: MARK.cy - MARK.size / 2 }}>
            <Mark size={MARK.size} color="#FFFFFF" spread={2.2 * (1 - slam)} rotate={-45 * (1 - slam)} glow={20 * flash} />
          </div>
          <div
            style={{
              position: "absolute",
              left: LOCKUP_AT.x,
              top: LOCKUP_AT.y,
              width: LOCKUP.w,
              height: LOCKUP.h,
              clipPath: `inset(0 0 0 ${(71.6 / 260.9) * 100}%)`,
              opacity: wordmark,
              transform: `translateX(${(1 - wordmark) * -40}px)`,
            }}
          >
            <Img src={brand("lockup-white.svg")} style={{ width: "100%", height: "100%" }} />
          </div>
        </>
      )}
      <div style={{ position: "absolute", left: 0, right: 0, top: 620, textAlign: "center" }}>
        <div style={{ fontFamily: WORDMARK, fontWeight: 700, fontSize: 40, color: C.ink, opacity: lines(18), letterSpacing: "-0.01em" }}>starwatch.danielvecera.com</div>
        <div style={{ ...label(20, C.teal), marginTop: 22, opacity: lines(30) }}>Open source · github.com/1vecera/starwatch</div>
        <div style={{ ...label(20, LABEL), marginTop: 14, opacity: lines(40) }}>Made by Daniel Večeřa · Prague</div>
      </div>
    </AbsoluteFill>
  );
};
