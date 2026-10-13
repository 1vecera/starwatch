---
target: Starwatch showreel v1 (video/src/showreel)
total_score: 9
max_score: 20
na_heuristics: 3,5,7,9,10
p0_count: 1
p1_count: 2
target_identity: "file:/home/vecera/code/agents007-hackathon/.claude/worktrees/sw-showreel/video/src/showreel"
timestamp: 2026-10-13T11-39-29Z
slug: video-src-showreel
---
Method: dual-agent (A: design review · B: detector + frame evidence). Also weighed: an earlier motion review (6/10 vs the Mluva reel) and a fact-check of every on-screen claim.

## Design health (non-interactive film; 3, 5, 7, 9, 10 n/a)

| # | Heuristic | Score | Key issue |
|---|---|---|---|
| 1 | Visibility of status | 2 | Orientation goes to meta (timecode, BPM, "/ 11"); city and candidate context left to tiny UI text |
| 2 | Match real world | 2 | Pipeline jargon (Apify Actors, DuckDB, S3 + CloudFront) speaks to developers, not voters or journalists |
| 4 | Consistency | 2 | Consistent with itself, contradicts the product's design system (ds.css: "No galaxy, no glow… white surfaces on slate") |
| 6 | Recognition vs recall | 2 | Feature names only in the 16 px HUD; captions vanish while captures scroll |
| 8 | Aesthetic & minimalist | 1 | About 11 text elements plus grain, grid, glow and brackets around an already dense UI |
| Total | | 9/20 | Poor |

## Design specificity verdict
Category-interchangeable. Swap the captures and logo and it is any AI/SaaS launch reel. The frame breaks Starwatch's own rules: night surface, glowing lifted teal #4FCBC2 instead of brand #0E6E6B, .16em tracked caps everywhere (the app uses .06em at 11 px). Tells: teal radial glow pulsing on the kick, drifting dot grid, grain, vignette, viewfinder brackets; spec-sheet HUD (SHOWREEL '26, timecode, 1920×1080 · 60 FPS · 128 BPM, beat diamonds, "/ 11", glowing progress bar); scramble text; word-by-word blur-rise; count-up counters; five numbered glass cards with a pulse dot; bracketed leader callouts; white flash, glowing marks, whip blur, logo slam with shake; identical slide-in/slide-out for four chapters; centred big-type cards and a word strobe.
Deterministic scan: 0 findings (20 files), but the detector cannot see inline style objects, which is how the whole reel is styled; a clean scan is no evidence here. Frames: 49% are dark text-on-black over a teal glow; 85% of overlay words are tracked capitals; 17 distinct font sizes; one near-blank frame at 0.5 s. Contrast passes (min 4.59). Browser overlay: not applicable to a rendered video.

## What's working
- Only real captures, disclosed; the flight from Czechia into Prague's party islands is footage only this product has.
- Careful data copy: "a snapshot, not live", "separate measures, never one score", "no polls, no forecasts".
- Authored ideas: the mark as the tagline's full stop, the app card opening into the Atlas on the drop, the end card from the real lockup file (pixel diff 0).

## Priority issues
- [P0] Wrong world and HUD costume. Fix: delete HUD, brackets, grain, grid, glow, vignette; rebuild on the app's canvas #F2F7F7 with its topographic contours (img/bg-topo.svg), brand #0E6E6B and its slate shadows. Command: /impeccable shape, then /impeccable quieter.
- [P1] The brag is the climax ("Overall champion" at 168 px, "built solo in one night", "One night"); the results were added after the vote, so "one night" also overstates. Fix: cut chapter 9 and "One night"; keep the win as one sentence-case line on the end card. Command: /impeccable distill.
- [P1] The product is framed, never shot: camera fixed at 0.94, only scrolls; islands, posts and votes never readable; captions carry it. Fix: full-frame, push into one Prague island, one candidate, one attention-vs-votes contrast with real names and numbers. Command: /impeccable animate.
- [P2] Type and copy: 16–17 px tracked caps, scramble, jargon; false or overstated lines ("Topic mix from reviewed labels", "Every number links back", Praha table labelled with all-city totals). Fix: sentence-case Schibsted 28–36 px, one caption at a time, plain fades, corrected claims, drop the pipeline chapter. Command: /impeccable typeset, /impeccable clarify.
- [P3] Craft: one-frame blank flicker at every screen change; scrolls ignore the beat; connector line through card titles; "Cloudflare" overflows card 05; callouts past the margin; ragged stat alignment; capture artefacts under the floating top bar. Command: /impeccable polish.

## Persona red flags
- Czech professional on LinkedIn, sound off, phone: tracked 14–17 px caps shrink to about 3 px; the first legible message is a timecode; the peak is a brag.
- Journalist checking a claim: sees "every number links back" and an all-city figure on Prague's table; trust drops.
- Voter from Brno: the film never says "look up your city"; the end card gives a URL, not a reason.

## Minor observations
- Display scale T in theme.ts is unused; sizes are hard-coded. brand and ink3 colours unused.
- Montage claims at 14 frames each are unreadable; "5,405", "10 cities", "4 platforms" repeat chapter 02.

## Questions to consider
- If the film lived entirely in the app's light, with no type above 40 px except the tagline, what would still be worth showing?
- Can one real contrast (the most-viewed candidate versus the one elected) carry the 45 seconds?
- Does it need the 128 BPM grid on display, or should the music serve the cut?
