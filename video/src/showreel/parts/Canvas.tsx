import { AbsoluteFill, useCurrentFrame } from "remotion";
import { asset, C } from "../theme";

// The app's page background (data.html): topographic contours over a faint grid on the slate canvas.
// The contours drift a few pixels over the film, the only motion that is not the camera.
export const Canvas: React.FC = () => {
  const frame = useCurrentFrame();
  return (
    <AbsoluteFill
      style={{
        backgroundColor: C.canvas,
        backgroundImage: `url(${asset("img/bg-topo.svg")}), url(${asset("img/bg-grid.svg")})`,
        backgroundSize: "cover, 192px 192px",
        backgroundPosition: `${-frame * 0.02}px ${-frame * 0.012}px, 0 0`,
        backgroundRepeat: "no-repeat, repeat",
      }}
    />
  );
};
