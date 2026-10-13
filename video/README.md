# Starwatch film '26

A 45-second, 1920×1080, 60 fps motion-design film of the live app, cut to a 128 BPM score. It keeps the app's light world (the slate canvas with its topographic contours, white sheets with the app's `--elev-3` shadow, ink, one teal, Bricolage Grotesque for display) and moves real pieces of the app as layers: the welcome wall's post tiles, both candidates' portraits, the map flight and short tool shots. Type slams in on the beat, counters roll to the app's exact numbers, and the star mark's blade is the brand wipe. The direction is recorded in `.impeccable/surfaces/video-src-showreel.md` and the product context in `PRODUCT.md`.

| Beats | Scene | Motion |
| --- | --- | --- |
| 0–6 | The mark's four blades fly in and lock; the app's tagline slams in | Blades from the four sides, a contour ring on the lock, masked word rises |
| 6–16 | The 48 most-viewed posts as a tilted 3D wall; the posts become a giant 12,595; then 5,405 candidates in ten cities | Dive through the mark, columns land from both sides and scroll like the app's wall, the number is filled with the same tiles and flies through the camera, a card rises |
| 14–24 | The Star Atlas rises as a sheet and lands flat on the first frame of the flight; "Who got the attention?"; Prague in a spotlight | 3D crane up, ring pulses on Prague |
| 24–31 | On the drop: the real camera flight into Prague, then its party islands | A teal disc from Prague opens into the flight, which hangs and then rushes in with a trail of its own frames; zoom punch, frame shake, beat punches |
| 31–39 | Tomáš Kaštovský, 1st by reach in Prague: 25M video views since 2023, 85,284 votes | Whip pan in, portrait in 3D, odometers |
| 39–47 | Petr Hlaváček, 1st by votes in Prague: 999k video views, 100,907 votes, the most in Prague | Whip pan, mirrored layout |
| 47–55 | Head to head: views and votes as bars from a centre line; "Most watched. Not most voted." | Portraits clash on the beat, bars grow toward each candidate |
| 55–64 | Spotlight, Pulse, Radar, By the numbers | Teal blade sweep, then one tool per two beats, each sheet entering a different way |
| 64–68 | The welcome screen on a phone: open to everyone, no sign-in | Phone drops in spinning and lands on the beat |
| 68–72 | Overall champion, Agents 0.0.7 hackathon, 38 projects | The film's only full-bleed teal, wiped in on a slant and lifted away |
| 72–80 | The ten cities as outlined rows; one fills with teal on every beat; "Look up your city." | Rows run in opposite directions, then clear |
| 80–96 | The app's 3D mark spins up with a contour ring on each beat and snaps into the lockup on the final hit | End card: the lockup, the address, the code and the author |

`src/showreel/timing.ts` holds the beat grid (`0.014 s + n × 0.46875 s`); `Showreel.tsx` holds the scene windows and the global contour lift and shake; each scene in `scenes/` keys its motion to beats. `parts/` holds the masked word slams and the odometer (`Kinetic.tsx`), the blade sweep (`Mark.tsx`), 3D cards (`Stage.tsx`) and the contour canvas (`Canvas.tsx`, from the app's `bg-topo.svg`).

## Real UI and honest claims

No screen is redrawn. `capture/capture.mjs` opens https://starwatch.danielvecera.com in headless Chromium with reduced motion: the map flight (with both side panels closed through the app's own buttons) and the tool pages as per-frame scripted camera or scroll positions, and the wall tiles and Spotlight portraits as element screenshots (3× and 5×). The reel only moves, scales and masks them. Kinetic type and the head-to-head bars are motion graphics of the app's own numbers: Spotlight's video views (since each account's first collected post in 2023) and the 2026 results from the Czech Statistical Office. The end card says "App footage: real captures of the live app".

The end card's lockup is `app/web/brand/lockup.svg` itself; `StarwatchLockupCheck` renders the resting end card against that file, and the pixel diff is zero.

## Build

Requires Node/npm, FFmpeg, uv and a Chromium build (`CHROME`). Captures and audio stay out of Git (`video/tmp/`, `video/public/showreel/`).

```sh
cd video
npm ci
CHROME=/path/to/chrome npm run capture     # tmp/captures/<take>/ (the map flight takes about 15 min; tiles and parts under a minute)
uv run showreel/prepare.py --audio <folder with score-4.mp3 and sfx/>
npm run render                             # silent picture → out/starwatch-showreel.mp4 (about 3 min)
npm run master                             # mix, master and mux → out/starwatch-showreel-master.mp4
npx remotion still src/index.ts StarwatchLockupCheck /tmp/svg.png --props='{"mode":"svg"}'
npx remotion still src/index.ts StarwatchLockupCheck /tmp/chapter.png --props='{"mode":"chapter"}'
magick compare -metric AE /tmp/svg.png /tmp/chapter.png null:   # 0
```

## Sound

The score is ElevenLabs Music v2.5, take 4 of four from one prompt ([flow](https://elevenlabs.io/app/flows/5UuhkrWsLlYeXmYy7dPT)). It starts 3.762 s into the take, two bars into its intro, so its drop lands on beat 24 (the flight into Prague) and its final hit on beat 88 (the end card). Eleven effects from the Mluva showreel's ElevenLabs sessions (impacts, whooshes, pops, a split-flap for the counters, a riser into the drop and the final hit) are placed by `mix.py` from `src/showreel/cues.json`, which masters to −14 LUFS with a −1.5 dBTP ceiling. Levels were set by analysis, not by ear.
