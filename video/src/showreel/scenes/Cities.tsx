import { AbsoluteFill, useCurrentFrame } from "remotion";
import { hBlur } from "../parts/Blur";
import { Letters, Words } from "../parts/Kinetic";
import { C, DISPLAY, easeIn, easeOut, expoOut, ramp, WORDMARK } from "../theme";
import { beatAt, beatFrame as F } from "../timing";

// The ten cities in the app (SW.cities), as rows of outlined names that run in opposite directions; on
// every beat the next city fills with teal. Then the rows sink behind the one line that matters.
const CITIES = ["Praha", "Brno", "Ostrava", "Plzeň", "Liberec", "Olomouc", "České Budějovice", "Hradec Králové", "Ústí nad Labem", "Pardubice"];
const ROWS = [0, 1, 2, 3, 4];
const SPEED = [7, -9, 6, -8, 7.5];
export const CITIES_OUT = F(76);
export const CTA_OUT = F(83);

export const Cities: React.FC = () => {
  const frame = useCurrentFrame();
  const lit = CITIES[(((Math.floor(beatAt(frame)) - 72) % 10) + 10) % 10];
  const row = (r: number, f: number) => {
    const dir = r % 2 ? -1 : 1;
    const enter = dir * 2400 * (1 - ramp(f, F(71.9) + r * 2, F(72.6) + r * 2, expoOut));
    return enter + (f - F(72)) * SPEED[r] - 1400 - r * 380;
  };
  // Behind the line, the rows sink to a texture and keep running, then fade before the mark.
  const dim = 1 - 0.82 * ramp(frame, CITIES_OUT, CITIES_OUT + 12, easeOut) - 0.18 * ramp(frame, CTA_OUT, CTA_OUT + 14, easeIn);
  return (
    <AbsoluteFill style={{ transform: "rotate(-5deg) scale(1.12)" }}>
      {frame < CTA_OUT + 16
        ? ROWS.map((r) => {
            const x = row(r, frame);
            const names = Array.from({ length: 4 }, () => CITIES.slice(r * 2).concat(CITIES.slice(0, r * 2))).flat();
            return (
              <div
                key={r}
                style={{ position: "absolute", top: 40 + r * 212, left: 0, whiteSpace: "nowrap", opacity: dim, transform: `translateX(${x}px)`, filter: hBlur(x - row(r, frame - 1)) }}
              >
                {names.map((name, i) => (
                  <span
                    key={i}
                    style={{
                      fontFamily: DISPLAY,
                      fontVariationSettings: "'opsz' 96",
                      fontWeight: 720,
                      fontSize: 150,
                      letterSpacing: "-0.036em",
                      marginRight: 90,
                      color: name === lit ? C.brand : "transparent",
                      WebkitTextStroke: name === lit ? undefined : `2px ${C.label}`,
                      opacity: name === lit ? 1 : 0.55,
                    }}
                  >
                    {name}
                  </span>
                ))}
              </div>
            );
          })
        : null}
      <AbsoluteFill style={{ transform: "rotate(5deg) scale(0.893)" }}>
        <div style={{ position: "absolute", top: 452, left: 0, width: 1920, textAlign: "center" }}>
          <Letters
            text="Look up your city."
            at={F(76.5)}
            step={1.2}
            out={CTA_OUT}
            style={{ fontFamily: DISPLAY, fontVariationSettings: "'opsz' 96", fontWeight: 720, fontSize: 168, letterSpacing: "-0.036em", lineHeight: 0.98, color: C.label }}
          />
        </div>
        <div style={{ position: "absolute", top: 660, left: 0, width: 1920, textAlign: "center" }}>
          <Words words={[{ text: "starwatch.danielvecera.com", at: F(78) }]} out={CTA_OUT} style={{ fontFamily: WORDMARK, fontWeight: 700, fontSize: 62, letterSpacing: "-0.01em", color: C.brand }} />
        </div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};
