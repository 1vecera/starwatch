import { AbsoluteFill, Img } from "remotion";
import { C, ELEV3 } from "../theme";

// A 3D stage: everything inside shares one camera (perspective from the frame centre).
export const Stage: React.FC<{ children: React.ReactNode; perspective?: number; style?: React.CSSProperties }> = ({ children, perspective = 1800, style }) => (
  <AbsoluteFill style={{ perspective, perspectiveOrigin: "960px 540px", ...style }}>
    <AbsoluteFill style={{ transformStyle: "preserve-3d" }}>{children}</AbsoluteFill>
  </AbsoluteFill>
);

export type Pose = { x: number; y: number; z?: number; rx?: number; ry?: number; rz?: number; s?: number };

export const transformOf = (p: Pose) =>
  `translate3d(${p.x}px, ${p.y}px, ${p.z ?? 0}px) rotateX(${p.rx ?? 0}deg) rotateY(${p.ry ?? 0}deg) rotateZ(${p.rz ?? 0}deg) scale(${p.s ?? 1})`;

// A white sheet (or a real capture) centred on (x, y) with the app's radius and --elev-3 shadow.
export const Card: React.FC<{
  pose: Pose;
  w: number;
  h: number;
  src?: string;
  radius?: number;
  opacity?: number;
  filter?: string;
  fit?: React.CSSProperties["objectFit"];
  position?: string;
  background?: string;
  shadow?: boolean;
  children?: React.ReactNode;
}> = ({ pose, w, h, src, radius = 20, opacity = 1, filter, fit = "cover", position = "50% 0%", background = C.surface, shadow = true, children }) => (
  <div
    style={{
      position: "absolute",
      left: -w / 2,
      top: -h / 2,
      width: w,
      height: h,
      transform: transformOf(pose),
      borderRadius: radius,
      overflow: "hidden",
      background,
      boxShadow: shadow ? `0 0 0 1px ${C.hairline}, ${ELEV3}` : undefined,
      opacity,
      filter,
      backfaceVisibility: "hidden",
    }}
  >
    {src ? <Img src={src} style={{ width: "100%", height: "100%", objectFit: fit, objectPosition: position, display: "block" }} /> : null}
    {children}
  </div>
);
