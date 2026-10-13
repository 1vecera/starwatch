# Starwatch showreel '26

A 45-second, 1920×1080, 60 fps product tour of the live app, cut to a 128 BPM score: 24 bars, eleven chapters. It follows the Mluva showreel's technique (Remotion, a beat grid every keyframe derives from, a HUD frame, callouts outside the UI, the logo at rest drawn from the brand file) and goes through every screen.

| Beats | Chapter | What it shows |
| --- | --- | --- |
| 0–8 | 01 Who's being heard | The mark glints; the welcome screen's tagline, one word per half beat, with the mark as its full stop |
| 8–16 | 02 The snapshot | 12,595 posts, 110 verified accounts, 10 cities, 4 platforms, next to the real welcome screen |
| 16–24 | 03 Pipeline | The README's "How it works": registry, Apify Actors, evidence graph, static app, hosting; the app node opens into the window on the drop |
| 24–36 | 04 Star Atlas | Czechia, a camera flight into Prague, the party islands, top posts and the official result |
| 36–44 | 05 Spotlight | Petr Hlaváček's page: his 2026 result next to his attention, down to his best posts |
| 44–52 | 06 Pulse | Head to head with three rivals, then 2022 votes, attention and the 2026 result side by side |
| 52–60 | 07 Radar | The watchlist and the snapshot replay feed |
| 60–72 | 08 2026 results | By the numbers: the snapshot, the official results per city, every list in Prague |
| 72–80 | 09 Hackathon | Overall champion and Social Media Deep Research winner at Agents 0.0.7 |
| 80–88 | 10 Open to everyone | Phone captures, then cuts on the beat and on eighth notes |
| 88–96 | 11 End card | The final hit: the lockup, the address, the code and the author |

`src/showreel/timing.ts` holds the beat grid (`0.014 s + n × 0.46875 s`); `theme.ts` holds the identity: a night surface, the app's ink, the brand teal lifted for dark (`#4FCBC2`), Bricolage Grotesque for display, Schibsted Grotesk for labels and Sora for the address, as in the app.

## Real UI and honest claims

No screen is redrawn. `capture/capture.mjs` opens https://starwatch.danielvecera.com in headless Chromium at 1600×900 CSS pixels and 1.5× density with reduced motion, so every frame is a settled state of the real app. Motion comes from a scripted camera, never from screen recording: for the Star Atlas the script sets the MapLibre camera for each frame (a zoom into Prague along a straight screen line) and waits until every tile has loaded; for the other screens it sets the scroll position and waits until the visible images have decoded. Then it takes the screenshot. The reel shows these PNGs one capture frame per reel frame and says on screen that the camera is scripted.

Callouts never cover captured pixels: a bracket sits just outside the window, spans the element it refers to, and the label runs into the margin.

The lockup animates the mark's four shards, then rests as `app/web/brand/lockup-white.svg` itself; `StarwatchLockupCheck` renders the resting end card against that file, and the pixel diff is zero.

Figures and wording come from the app and the repository: the snapshot counts from By the numbers, the pipeline from the README's "How it works", the result from hq.agents007.ai/results, and the claims in the montage (no sign-in, MIT, a snapshot, no polls or forecasts, owners verified) from the README.

## Build

Requires Node/npm, FFmpeg, uv and a Chromium build (`CHROME`). Captures and audio stay out of Git (`video/tmp/`, `video/public/showreel/`).

```sh
cd video
npm ci
CHROME=/path/to/chrome npm run capture     # tmp/captures/<take>/ (map flight: about 15 min)
uv run showreel/prepare.py --audio <folder with score-4.mp3 and sfx/>
npm run render                             # silent picture → out/starwatch-showreel.mp4
npm run master                             # mix, master and mux → out/starwatch-showreel-master.mp4
npx remotion still src/index.ts StarwatchLockupCheck /tmp/svg.png --props='{"mode":"svg"}'
npx remotion still src/index.ts StarwatchLockupCheck /tmp/chapter.png --props='{"mode":"chapter"}'
magick compare -metric AE /tmp/svg.png /tmp/chapter.png null:   # 0
```

## Sound

The score is ElevenLabs Music v2.5, take 4 of four from one prompt ([flow](https://elevenlabs.io/app/flows/5UuhkrWsLlYeXmYy7dPT)). It starts 3.762 s into the take, two bars into its intro, so its drop lands on beat 24 (the Star Atlas) and its final hit on beat 88 (the lockup). The effects are the Mluva showreel's ElevenLabs takes, reused. `mix.py` places them from `src/showreel/cues.json` sample-accurately, masters to −14 LUFS with a −1.5 dBTP ceiling and muxes 320 kbit/s AAC. Effect levels were set by analysis, not by ear.
