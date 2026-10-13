// Directional blur for fast moves: SVG filters referenced by id, picked by the nearest strength.
const STEPS = [3, 6, 12, 22, 40, 70];

export const BlurDefs: React.FC = () => (
  <svg width={0} height={0} style={{ position: "absolute" }}>
    <defs>
      {STEPS.map((s) => (
        <filter key={`h${s}`} id={`hblur-${s}`} x="-30%" y="-5%" width="160%" height="110%">
          <feGaussianBlur stdDeviation={`${s} 0`} />
        </filter>
      ))}
      {STEPS.map((s) => (
        <filter key={`v${s}`} id={`vblur-${s}`} x="-5%" y="-30%" width="110%" height="160%">
          <feGaussianBlur stdDeviation={`0 ${s}`} />
        </filter>
      ))}
    </defs>
  </svg>
);

const pick = (amount: number) => STEPS.reduce((best, s) => (Math.abs(s - amount) < Math.abs(best - amount) ? s : best), STEPS[0]);

// `speed` in px per frame; a 180° shutter smears about half of it.
export const hBlur = (speed: number) => (Math.abs(speed) * 0.5 < 2 ? undefined : `url(#hblur-${pick(Math.abs(speed) * 0.5)})`);
export const vBlur = (speed: number) => (Math.abs(speed) * 0.5 < 2 ? undefined : `url(#vblur-${pick(Math.abs(speed) * 0.5)})`);
