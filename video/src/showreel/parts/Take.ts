import { asset } from "../theme";

// One captured frame of a take (see capture/capture.mjs); stills are frame 0.
export const shot = (take: string, index = 0) => asset(`${take}/${String(index).padStart(4, "0")}.png`);
