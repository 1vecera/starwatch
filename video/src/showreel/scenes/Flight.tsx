import { AbsoluteFill, Img, useCurrentFrame } from "remotion";
import { hBlur } from "../parts/Blur";
import { shot } from "../parts/Take";
import { kick, whip } from "../parts/track";
import { C, clamp01, expoOut, ramp } from "../theme";
import { beatFrame as F } from "../timing";
import { PRAHA } from "./Czechia";

// The drop: the teal disc opens from Prague onto the real camera flight into the city, one captured
// frame per reel frame, then Prague's party lists as islands of their posts. The capture is cropped in
// (1.3×) so the app's header and attribution fall off the frame; a zoom punch lands the drop, the
// kicks punch the islands, and a whip pan on beat 32 leaves for the comparison.
export const WHIP_AT = F(32);

export const flightIndex = (frame: number) => (frame < F(28) ? Math.min(109, Math.max(0, frame - F(24))) : 110 + Math.min(169, frame - F(28)));
export const flightX = (frame: number) => -1920 * whip(frame, WHIP_AT);

export const Flight: React.FC = () => {
  const frame = useCurrentFrame();
  const t = clamp01((frame - F(24)) / 16);
  const islands = frame >= F(28);
  const punch = 0.16 * (1 - expoOut(t)) + 0.04 * (kick(frame, F(28), 16) + kick(frame, F(30), 16));
  const push = islands ? 0.18 * ramp(frame, F(28), F(31.5), (x) => x) : 0;
  const s = 1.3 + punch + push;
  const x = flightX(frame);
  const iris = 1500 * expoOut(clamp01((frame - F(24)) / 12));
  return (
    <AbsoluteFill style={{ transform: `translateX(${x}px)`, filter: hBlur(x - flightX(frame - 1)), overflow: "hidden" }}>
      <Img
        src={shot("atlas", flightIndex(frame))}
        style={{ position: "absolute", inset: 0, width: 1920, height: 1080, transform: `scale(${s})`, transformOrigin: islands ? "620px 500px" : `${PRAHA.x}px ${PRAHA.y}px` }}
      />
      {iris < 1499 ? (
        <AbsoluteFill style={{ background: `radial-gradient(circle at ${PRAHA.x}px ${PRAHA.y}px, transparent ${iris}px, ${C.brand} ${iris + 1}px)` }} />
      ) : null}
    </AbsoluteFill>
  );
};
