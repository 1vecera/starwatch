import { AbsoluteFill, useCurrentFrame } from "remotion";
import { at, CHAPTERS } from "../timing";
import { C, DISPLAY, easeIn, easeInOut, easeOut, label, LABEL, ramp } from "../theme";
import { WIN } from "../parts/Window";

// How a post gets into the app, from the README's "How it works": one stage per beat.
const NODES = [
  { title: "Official registry", sub: "2026 candidacies · 2022 results" },
  { title: "Apify Actors", sub: "Public posts, profiles, media · hard cost caps" },
  { title: "Evidence graph", sub: "DuckDB · owner confirmed by an independent source" },
  { title: "Static app", sub: "HTML, CSS, JS · MapLibre · ECharts" },
  { title: "Open to everyone", sub: "S3 + CloudFront behind Cloudflare" },
];
const W = 276;
const H = 168;
const GAP = 40;
const LEFT = (1920 - (NODES.length * W + (NODES.length - 1) * GAP)) / 2;
const TOP = 420;
const LENGTH = CHAPTERS[2].to - CHAPTERS[2].from;
const lerp = (a: number, b: number, t: number) => a + (b - a) * t;

export const C03Pipeline: React.FC = () => {
  const frame = useCurrentFrame();
  const line = ramp(frame, at(3, 16.4), at(3, 21), easeInOut);
  // The riser: the app node opens into the window that the Star Atlas fills on the drop.
  const open = ramp(frame, at(3, 22.5), LENGTH, easeIn);
  const others = 1 - ramp(frame, at(3, 22), at(3, 23), easeIn);
  const app = 3;
  const ax = LEFT + app * (W + GAP);
  const box = { x: lerp(ax, WIN.x, open), y: lerp(TOP, WIN.y, open), w: lerp(W, WIN.w, open), h: lerp(H, WIN.h, open) };
  return (
    <AbsoluteFill>
      <div style={{ ...label(18, LABEL), position: "absolute", left: LEFT, top: 320, opacity: ramp(frame, 4, 14) * others }}>How it works</div>
      <svg width={1920} height={1080} style={{ position: "absolute", inset: 0, opacity: others }}>
        <line x1={LEFT + W / 2} y1={TOP + H / 2} x2={LEFT + W / 2 + (NODES.length - 1) * (W + GAP) * line} y2={TOP + H / 2} stroke={C.line} strokeWidth={2} />
        {NODES.slice(0, -1).map((_, i) => {
          // A pulse runs along each link on the beat after its node lands.
          const p = ramp(frame, at(3, 17 + i), at(3, 17.8 + i), easeInOut);
          if (p <= 0 || p >= 1) return null;
          const x = LEFT + W / 2 + (i + p) * (W + GAP);
          return <circle key={i} cx={x} cy={TOP + H / 2} r={5} fill={C.teal} style={{ filter: `drop-shadow(0 0 8px ${C.tealGlow})` }} />;
        })}
      </svg>
      {NODES.map((n, i) => {
        const start = at(3, 16.5 + i);
        const t = ramp(frame, start, start + 12, easeOut);
        const isApp = i === app;
        const x = LEFT + i * (W + GAP);
        const style: React.CSSProperties = isApp && open > 0
          ? { left: box.x, top: box.y, width: box.w, height: box.h, background: `rgba(242,247,247,${open})` }
          : { left: x, top: TOP, width: W, height: H, opacity: isApp ? t : t * others };
        return (
          <div
            key={n.title}
            style={{
              position: "absolute",
              ...style,
              borderRadius: isApp ? 14 : 12,
              border: `1px solid ${isApp ? C.teal : C.line}`,
              background: style.background ?? "rgba(238,244,244,0.035)",
              boxShadow: isApp ? `0 0 ${40 + 60 * open}px rgba(79,203,194,${0.18 + 0.2 * open})` : "none",
              transform: open > 0 ? undefined : `translateY(${(1 - t) * 26}px)`,
              padding: "22px 22px",
              boxSizing: "border-box",
            }}
          >
            <div style={{ opacity: 1 - open * 3 }}>
              <div style={{ ...label(14, isApp ? C.teal : LABEL) }}>{String(i + 1).padStart(2, "0")}</div>
              <div style={{ fontFamily: DISPLAY, fontWeight: 750, fontSize: 32, letterSpacing: "-0.02em", color: C.ink, marginTop: 10, lineHeight: 1.05 }}>{n.title}</div>
              <div style={{ fontFamily: "'Schibsted Grotesk', sans-serif", fontSize: 18, lineHeight: 1.35, color: C.ink2, marginTop: 10 }}>{n.sub}</div>
            </div>
          </div>
        );
      })}
      <div style={{ ...label(20, C.teal), position: "absolute", left: 0, right: 0, top: 660, textAlign: "center", opacity: ramp(frame, at(3, 21), at(3, 21.4)) * others }}>
        Every number links back to the post it came from
      </div>
    </AbsoluteFill>
  );
};
