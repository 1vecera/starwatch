# Starwatch film '26

A 45-second, 1920×1080, 60 fps film of the live app, cut to a 128 BPM score. It is set in the app's own page: the slate canvas with its topographic contours, one rounded sheet of real app footage with the app's `--elev-3` shadow, and one sentence-case caption at a time under it. There is no HUD, glow or title graphics; the camera does the storytelling by easing onto names and numbers in the real UI. The direction is recorded in `.impeccable/surfaces/video-src-showreel.md` and the product context in `PRODUCT.md`.

| Beats | Shot | Caption |
| --- | --- | --- |
| 0–8 | The welcome screen's wall of campaign posts, easing toward the tagline card | Candidates' public posts in ten Czech cities, before the 2026 vote. |
| 8–24 | Star Atlas over Czechia, drifting toward Prague | Each city sized by the attention its candidates got. · Collected 8–9 October 2026. A snapshot, not live. |
| 24–28 | On the drop: the real camera flight into Prague | Fly into a city. |
| 28–36 | Prague's lists as islands of their posts, then in to SPOLU pro Prahu | Each list becomes an island of its posts. · Most reach in Prague: SPOLU pro Prahu, 26M. |
| 36–44 | Tomáš Kaštovský's Spotlight: his views, then his 2026 result | 25M video views since 2023. · 85,284 votes. Elected, 11th by votes on his list. |
| 44–52 | Petr Hlaváček's Spotlight: his views, then his 2026 result | 999k video views since 2023. · 100,907 votes, the most in Prague. |
| 52–60 | Pulse with the two side by side, down to attention next to votes | Pulse puts them side by side. · Attention and votes: separate measures, never one score. |
| 60–68 | By the numbers: official results per city, then every list in Prague | Official 2026 results, final count. · All 5,405 candidates, next to what they posted. |
| 68–72 | The welcome screen on a phone | Open to everyone. No sign-in. |
| 72–76 | One plain line about the hackathon | Built at the Agents 0.0.7 hackathon in Prague. Overall winner among 38 projects. |
| 76–88 | The Atlas again, in on the list of ten cities | Look up your city at starwatch.danielvecera.com. · Open source under MIT on GitHub. |
| 88–96 | The final hit: the lockup, the address, the code and the author | |

`src/showreel/timing.ts` holds the beat grid (`0.014 s + n × 0.46875 s`); `Showreel.tsx` holds the shots (capture, frame mapping, camera keys in the page's CSS pixels) and the captions. `theme.ts` carries the app's tokens from `app/web/ds.css`.

## Real UI and honest claims

No screen is redrawn. `capture/capture.mjs` opens https://starwatch.danielvecera.com in headless Chromium at 1600×900 CSS pixels with reduced motion, so every frame is a settled state of the real app, and the pointer rests on an empty margin. Motion inside the app comes from a scripted camera, never from screen recording: for the Star Atlas the script sets the MapLibre camera for each frame and waits until every tile has loaded; for scrolling screens it sets the scroll position and waits until visible images have decoded. Stills the camera pushes into (the welcome screen, both Spotlight pages, Pulse) are captured at 2.5× density so names and numbers stay sharp. The film says "Real captures of the live app" under every app shot.

The comparison uses the app's own numbers: Spotlight's video views (since each account's first collected post in 2023) and its 2026 result from the Czech Statistical Office, and Pulse's side-by-side table. The film follows the app in keeping attention and votes as separate measures.

The end card's lockup is `app/web/brand/lockup.svg` itself; `StarwatchLockupCheck` renders the resting end card against that file, and the pixel diff is zero.

## Build

Requires Node/npm, FFmpeg, uv and a Chromium build (`CHROME`). Captures and audio stay out of Git (`video/tmp/`, `video/public/showreel/`).

```sh
cd video
npm ci
CHROME=/path/to/chrome npm run capture     # tmp/captures/<take>/ (the map flight takes about 15 min)
uv run showreel/prepare.py --audio <folder with score-4.mp3 and sfx/>
npm run render                             # silent picture → out/starwatch-showreel.mp4
npm run master                             # mix, master and mux → out/starwatch-showreel-master.mp4
npx remotion still src/index.ts StarwatchLockupCheck /tmp/svg.png --props='{"mode":"svg"}'
npx remotion still src/index.ts StarwatchLockupCheck /tmp/chapter.png --props='{"mode":"chapter"}'
magick compare -metric AE /tmp/svg.png /tmp/chapter.png null:   # 0
```

## Sound

The score is ElevenLabs Music v2.5, take 4 of four from one prompt ([flow](https://elevenlabs.io/app/flows/5UuhkrWsLlYeXmYy7dPT)). It starts 3.762 s into the take, two bars into its intro, so its drop lands on beat 24 (the flight into Prague) and its final hit on beat 88 (the end card). Three effects (a sub-bass impact, a long one and a soft whoosh, from the Mluva showreel's takes) are placed by `mix.py` from `src/showreel/cues.json`, which masters to −14 LUFS with a −1.5 dBTP ceiling. Levels were set by analysis, not by ear.
