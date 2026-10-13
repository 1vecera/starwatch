import { Img } from "remotion";
import { C, ELEV3 } from "../theme";

// The sheet: one rounded app window on the canvas, always in the same place. Captures are
// 1600×900 CSS pixels; the camera picks a scale `m` (1 = the sheet's width) and the CSS point
// (cx, cy) to centre, clamped so the capture always covers the sheet.
export const VIEW = { x: 56, y: 56, w: 1808, h: 832 };
export const CSS = { w: 1600, h: 900 };
const BASE = Math.max(VIEW.w / CSS.w, VIEW.h / CSS.h);

export type Cam = { m: number; cx: number; cy: number };

export const frameCam = (cam: Cam) => {
  const k = BASE * cam.m;
  const w = CSS.w * k;
  const h = CSS.h * k;
  const left = Math.min(0, Math.max(VIEW.w - w, VIEW.w / 2 - cam.cx * k));
  const top = Math.min(0, Math.max(VIEW.h - h, VIEW.h / 2 - cam.cy * k));
  return { left, top, w, h };
};

export const Sheet: React.FC<{ src: string; cam: Cam; under?: string; mix?: number; opacity?: number }> = ({ src, cam, under, mix = 1, opacity = 1 }) => {
  const f = frameCam(cam);
  const img: React.CSSProperties = { position: "absolute", left: f.left, top: f.top, width: f.w, height: f.h, maxWidth: "none" };
  return (
    <div
      style={{
        position: "absolute",
        left: VIEW.x,
        top: VIEW.y,
        width: VIEW.w,
        height: VIEW.h,
        borderRadius: 18,
        overflow: "hidden",
        background: C.canvas,
        boxShadow: `0 0 0 1px ${C.hairline}, ${ELEV3}`,
        opacity,
      }}
    >
      {under && mix < 1 ? <Img src={under} style={img} /> : null}
      <Img src={src} style={{ ...img, opacity: under ? mix : 1 }} />
    </div>
  );
};
