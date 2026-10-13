// The reel runs on the score's 128 BPM grid: 96 beats, 24 bars, 45 s. The score starts 3.762 s into
// ElevenLabs take 4 (two bars of its intro are skipped), so its first kick lands 14 ms into the reel.
export const FPS = 60;
export const WIDTH = 1920;
export const HEIGHT = 1080;
export const DURATION = 2700;
export const BPM = 128;
export const BEAT = 60 / BPM;
export const GRID_OFFSET = 0.014;

export const beatTime = (beat: number) => GRID_OFFSET + beat * BEAT;
export const beatFrame = (beat: number) => Math.round(beatTime(beat) * FPS);
export const beatAt = (frame: number) => (frame / FPS - GRID_OFFSET) / BEAT;

export type Chapter = { index: number; name: string; from: number; to: number; beats: [number, number] };

// [name, first beat]; each chapter runs to the next one's first beat. The drop is beat 24, the final hit beat 88.
const plan: [string, number][] = [
  ["WHO'S BEING HEARD", 0],
  ["THE SNAPSHOT", 8],
  ["PIPELINE", 16],
  ["STAR ATLAS", 24],
  ["SPOTLIGHT", 36],
  ["PULSE", 44],
  ["RADAR", 52],
  ["2026 RESULTS", 60],
  ["HACKATHON", 72],
  ["OPEN TO EVERYONE", 80],
  ["END CARD", 88],
];

export const CHAPTERS: Chapter[] = plan.map(([name, beat], i) => {
  const next = plan[i + 1]?.[1] ?? 96;
  return {
    index: i + 1,
    name,
    from: i === 0 ? 0 : beatFrame(beat),
    to: i === plan.length - 1 ? DURATION : beatFrame(next),
    beats: [beat, next],
  };
});

export const chapterAt = (frame: number) =>
  CHAPTERS.find((chapter) => frame >= chapter.from && frame < chapter.to) ?? CHAPTERS[CHAPTERS.length - 1];

// Frames from a chapter's start to a beat inside it.
export const at = (chapter: number, beat: number) => beatFrame(beat) - CHAPTERS[chapter - 1].from;
