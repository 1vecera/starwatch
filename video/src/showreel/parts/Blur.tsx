// Directional (horizontal/vertical) blur for whip transitions without re-rendering video frames.
export const BlurDefs: React.FC = () => (
  <svg width={0} height={0} style={{ position: "absolute" }}>
    <defs>
      {[4, 10, 20, 36, 60].map((amount) => (
        <filter key={`h${amount}`} id={`hblur-${amount}`} x="-20%" y="0" width="140%" height="100%">
          <feGaussianBlur stdDeviation={`${amount} 0`} />
        </filter>
      ))}
      {[4, 10, 20, 36, 60].map((amount) => (
        <filter key={`v${amount}`} id={`vblur-${amount}`} x="0" y="-20%" width="100%" height="140%">
          <feGaussianBlur stdDeviation={`0 ${amount}`} />
        </filter>
      ))}
    </defs>
  </svg>
);

export const hBlur = (amount: number) => {
  const steps = [4, 10, 20, 36, 60];
  if (amount < 2) return "none";
  const step = steps.reduce((best, s) => (Math.abs(s - amount) < Math.abs(best - amount) ? s : best), steps[0]);
  return `url(#hblur-${step})`;
};

export const vBlur = (amount: number) => {
  const steps = [4, 10, 20, 36, 60];
  if (amount < 2) return "none";
  const step = steps.reduce((best, s) => (Math.abs(s - amount) < Math.abs(best - amount) ? s : best), steps[0]);
  return `url(#vblur-${step})`;
};
