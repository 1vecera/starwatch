import { Img } from "remotion";
import { C } from "../theme";

// The app window: a real capture (1600×900 CSS px at 1.5×) shown at WIN size in the reel frame.
export const CSS_W = 1600;
export const CSS_H = 900;
export const WIN = { x: 270, y: 152, w: 1380, h: (1380 * CSS_H) / CSS_W };
export const K = WIN.w / CSS_W; // reel px per CSS px

// A camera inside the window: scale `s` around the window centre, then shift by (dx, dy) reel px.
export type Cam = { s: number; dx: number; dy: number };
export const NO_CAM: Cam = { s: 1, dx: 0, dy: 0 };

// Where a CSS-pixel point of the capture lands in the reel frame under a camera.
export const place = (x: number, y: number, cam: Cam = NO_CAM) => {
  const cx = WIN.x + WIN.w / 2;
  const cy = WIN.y + WIN.h / 2;
  return { x: cx + (WIN.x + x * K - cx) * cam.s + cam.dx, y: cy + (WIN.y + y * K - cy) * cam.s + cam.dy };
};

// The window's own edges under a camera, for callouts that sit just outside it.
export const edges = (cam: Cam = NO_CAM) => {
  const a = place(0, 0, cam);
  const b = place(CSS_W, CSS_H, cam);
  return { left: a.x, top: a.y, right: b.x, bottom: b.y };
};

export const Window: React.FC<{
  src: string;
  cam?: Cam;
  opacity?: number;
  under?: string; // an earlier frame to dissolve from
  mix?: number;
  style?: React.CSSProperties;
}> = ({ src, cam = NO_CAM, opacity = 1, under, mix = 1, style }) => {
  const e = edges(cam);
  const box: React.CSSProperties = { position: "absolute", left: e.left, top: e.top, width: e.right - e.left, height: e.bottom - e.top };
  return (
    <div style={{ position: "absolute", inset: 0, opacity, ...style }}>
      <div
        style={{
          ...box,
          borderRadius: 14 * cam.s,
          boxShadow: `0 0 0 1px ${C.line}, 0 50px 140px rgba(0,0,0,0.65), 0 0 120px rgba(79,203,194,0.06)`,
        }}
      />
      <div style={{ ...box, borderRadius: 14 * cam.s, overflow: "hidden", background: "#F2F7F7" }}>
        {under && mix < 1 ? <Img src={under} style={{ position: "absolute", inset: 0, width: "100%", height: "100%" }} /> : null}
        <Img src={src} style={{ position: "absolute", inset: 0, width: "100%", height: "100%", opacity: under ? mix : 1 }} />
      </div>
    </div>
  );
};
