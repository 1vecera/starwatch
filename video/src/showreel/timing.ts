// The film runs on the score's 128 BPM grid: 96 beats, 24 bars, 45 s. The score starts 3.762 s into
// ElevenLabs take 4 (two bars of its intro are skipped), so its first kick lands 14 ms into the film.
// Cuts land on bars; the drop is beat 24 (the flight into Prague) and the final hit beat 88 (the end card).
export const FPS = 60;
export const WIDTH = 1920;
export const HEIGHT = 1080;
export const DURATION = 2700;
export const BPM = 128;
export const BEAT = 60 / BPM;
export const GRID_OFFSET = 0.014;

export const beatTime = (beat: number) => GRID_OFFSET + beat * BEAT;
export const beatFrame = (beat: number) => (beat <= 0 ? 0 : Math.round(beatTime(beat) * FPS));
export const beatAt = (frame: number) => (frame / FPS - GRID_OFFSET) / BEAT;
