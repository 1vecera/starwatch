import { AbsoluteFill, useCurrentFrame } from "remotion";
import { asset, C, clamp01 } from "../theme";
import { TOPO } from "./topo";

// The app's page background (data.html): topographic contours over a faint grid on the slate canvas.
// The contours are the app's own file, split per line so they can draw on from the centre out and
// lift with the kick; the grid stays as the app sets it.
const CENTRE = { x: 960, y: 600 };
const LINES = TOPO.flatMap((layer, li) =>
  layer.paths.map((d) => {
    const [x, y] = d.slice(1).split(/[ L]/).map(Number);
    return { d, li, reach: Math.hypot(x - CENTRE.x, y - CENTRE.y) / 1100 };
  }),
);

export const Canvas: React.FC<{ draw?: number; lift?: number; zoom?: number; dx?: number; dy?: number }> = ({
  draw = 1,
  lift = 0,
  zoom = 1,
  dx = 0,
  dy = 0,
}) => {
  const frame = useCurrentFrame();
  return (
    <AbsoluteFill style={{ backgroundColor: C.canvas, overflow: "hidden" }}>
      <AbsoluteFill
        style={{
          backgroundImage: `url(${asset("img/bg-grid.svg")})`,
          backgroundSize: `${192 * zoom}px ${192 * zoom}px`,
          backgroundPosition: `${960 - 960 * zoom + dx * 0.5}px ${540 - 540 * zoom + dy * 0.5}px`,
          opacity: clamp01(draw * 1.5),
        }}
      />
      <svg
        width={1920}
        height={1200}
        viewBox="0 0 1920 1200"
        style={{
          position: "absolute",
          left: 0,
          top: -60,
          transform: `translate(${dx - frame * 0.03}px, ${dy - frame * 0.015}px) scale(${zoom})`,
          transformOrigin: "960px 600px",
        }}
      >
        <g fill="none" strokeLinejoin="round" strokeLinecap="round">
          {LINES.map((line, i) => {
            const layer = TOPO[line.li];
            const shown = clamp01((draw * 1.7 - line.reach) / 0.7);
            if (shown <= 0) return null;
            const teal = layer.stroke !== "#0F172A";
            const opacity = layer.opacity * (1 + lift * (teal ? 2.6 : 0.9));
            return (
              <path
                key={i}
                d={line.d}
                stroke={layer.stroke}
                strokeOpacity={Math.min(0.5, opacity)}
                strokeWidth={layer.width * (1 + lift * (teal ? 0.8 : 0.2))}
                pathLength={1}
                strokeDasharray={shown < 1 ? "1 1" : undefined}
                strokeDashoffset={shown < 1 ? 1 - shown : undefined}
              />
            );
          })}
        </g>
      </svg>
    </AbsoluteFill>
  );
};
