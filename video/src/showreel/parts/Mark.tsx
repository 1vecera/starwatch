import { C } from "../theme";

// The Starwatch mark: four shards around a centre, from app/web/brand/mark.svg (viewBox -32 -32 64 64).
export const MARK_PATH =
  "M-30,0L-10.06,8.55L-6.77,-1.31L-5.21,-0.79L-0.91,-5.09L-10.59,-8.32ZM0,30L8.55,10.06L-1.31,6.77L-0.79,5.21L-5.09,0.91L-8.32,10.59ZM30,0L10.06,-8.55L6.77,1.31L5.21,0.79L0.91,5.09L10.59,8.32ZM0,-30L-8.55,-10.06L1.31,-6.77L0.79,-5.21L5.09,-0.91L8.32,-10.59Z";
// The same mark split into its four shards, so they can fly in separately.
export const SHARDS = MARK_PATH.split("Z").filter(Boolean).map((d) => `${d}Z`);

export const Mark: React.FC<{
  size: number;
  color?: string;
  rotate?: number;
  spread?: number;
  glow?: number;
  style?: React.CSSProperties;
}> = ({ size, color = C.teal, rotate = 0, spread = 0, glow = 0, style }) => {
  const dirs = [
    [-1, 0],
    [0, 1],
    [1, 0],
    [0, -1],
  ];
  return (
    <svg
      width={size}
      height={size}
      viewBox="-32 -32 64 64"
      style={{ overflow: "visible", transform: `rotate(${rotate}deg)`, filter: glow ? `drop-shadow(0 0 ${glow}px ${C.tealGlow})` : undefined, ...style }}
    >
      {SHARDS.map((d, i) => (
        <path key={i} d={d} fill={color} transform={`translate(${dirs[i][0] * spread * 30} ${dirs[i][1] * spread * 30})`} />
      ))}
    </svg>
  );
};
