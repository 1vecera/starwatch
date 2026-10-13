---
name: Starwatch
description: What Czech municipal candidates posted, the attention it got, and the votes they won, shown side by side on a slate schematic.
colors:
  brand-teal: "#0E6E6B"
  brand-teal-hover: "#0B5F5C"
  brand-teal-press: "#094F4C"
  brand-teal-soft: "#E3F1F0"
  slate-canvas: "#F2F7F7"
  surface: "#FFFFFF"
  surface-hi: "#EEF4F4"
  sunken: "#EAF1F0"
  ink: "#0F172A"
  ink-secondary: "#475569"
  ink-tertiary: "#5B6A7E"
  hairline: "rgba(22,37,36,.10)"
  hairline-strong: "rgba(22,37,36,.18)"
  status-orange: "#A84E08"
  status-cyan: "#0369A1"
  status-green: "#13783A"
  status-red: "#B91C1C"
typography:
  hero:
    fontFamily: "'Bricolage Grotesque', 'Schibsted Grotesk', system-ui, sans-serif"
    fontSize: "60px"
    fontWeight: 720
    lineHeight: 1.06
    letterSpacing: "-.032em"
  display:
    fontFamily: "'Bricolage Grotesque', 'Schibsted Grotesk', system-ui, sans-serif"
    fontSize: "48px"
    fontWeight: 720
    lineHeight: 1.06
    letterSpacing: "-.026em"
  headline:
    fontFamily: "'Bricolage Grotesque', 'Schibsted Grotesk', system-ui, sans-serif"
    fontSize: "30px"
    fontWeight: 700
    lineHeight: 1.15
    letterSpacing: "-.02em"
  headline-sm:
    fontFamily: "'Bricolage Grotesque', 'Schibsted Grotesk', system-ui, sans-serif"
    fontSize: "24px"
    fontWeight: 650
    lineHeight: 1.2
    letterSpacing: "-.018em"
  title:
    fontFamily: "'Bricolage Grotesque', 'Schibsted Grotesk', system-ui, sans-serif"
    fontSize: "20px"
    fontWeight: 650
    letterSpacing: "-.015em"
  lead:
    fontFamily: "'Schibsted Grotesk', -apple-system, BlinkMacSystemFont, 'Segoe UI', system-ui, sans-serif"
    fontSize: "16px"
    fontWeight: 400
    lineHeight: 1.6
  body:
    fontFamily: "'Schibsted Grotesk', -apple-system, BlinkMacSystemFont, 'Segoe UI', system-ui, sans-serif"
    fontSize: "14.5px"
    fontWeight: 400
    lineHeight: 1.5
    letterSpacing: "-.005em"
  label:
    fontFamily: "'Schibsted Grotesk', -apple-system, BlinkMacSystemFont, 'Segoe UI', system-ui, sans-serif"
    fontSize: "13px"
    fontWeight: 550
    letterSpacing: "0"
  wordmark:
    fontFamily: "'Sora', 'Inter', system-ui, sans-serif"
    fontWeight: 600
    letterSpacing: "-.01em"
rounded:
  chip: "6px"
  control: "8px"
  md: "10px"
  card: "12px"
  panel: "16px"
  sheet: "20px"
  xl: "24px"
  pill: "999px"
spacing:
  3xs: "2px"
  2xs: "4px"
  xs: "8px"
  sm: "12px"
  md: "16px"
  lg: "24px"
  xl: "32px"
  2xl: "48px"
  3xl: "64px"
  4xl: "96px"
components:
  button-primary:
    backgroundColor: "{colors.brand-teal}"
    textColor: "{colors.surface}"
    rounded: "{rounded.control}"
    padding: "0 12px"
    height: "32px"
  button-primary-hover:
    backgroundColor: "{colors.brand-teal-hover}"
  button-primary-active:
    backgroundColor: "{colors.brand-teal-press}"
  button-secondary:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink}"
    rounded: "{rounded.control}"
    padding: "0 12px"
    height: "32px"
  button-secondary-hover:
    backgroundColor: "{colors.surface-hi}"
  chip:
    backgroundColor: "{colors.sunken}"
    textColor: "{colors.ink-secondary}"
    rounded: "{rounded.chip}"
    padding: "0 9px"
    height: "24px"
  chip-on:
    backgroundColor: "{colors.brand-teal-soft}"
    textColor: "{colors.brand-teal}"
  segmented:
    backgroundColor: "{colors.sunken}"
    rounded: "{rounded.control}"
    padding: "2px"
  segmented-on:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink}"
    rounded: "{rounded.chip}"
    height: "28px"
  card:
    backgroundColor: "{colors.surface}"
    rounded: "{rounded.card}"
    padding: "16px"
  chrome-pill:
    rounded: "{rounded.pill}"
    height: "46px"
---

# Design System: Starwatch

## Overview

**Creative North Star: "The Slate Schematic"**

Starwatch is drawn like a survey sheet: white surfaces laid on a pale slate canvas, a faint topographic contour field and grid behind them, minimum ink and exact information. The stylesheet states the doctrine in its first line: "No galaxy, no glow, no yellow." Depth is a quiet stack of slate-tinted shadows, not light; emphasis is one teal, not saturation. The system was rebuilt into this light language (Atlas C, accepted 9 October 2026) from an earlier dark, glassy one, and the override layer still forcibly removes the sky canvas, glows, halos and text shadows from screens first drawn in that language.

Data encoding is part of the visual system and is fixed across screens: colour says who posted (party), shape says how (platform or format), area is the stated metric, and a dashed outline means not observed. Because attention and votes are separate measures, they sit next to each other and are never merged into one figure or one visual weight.

The density is an analyst's: a fixed pixel type scale tuned for UI, tight body steps, proportional numerals by default and tabular numerals only where columns align. Motion is exponential ease-out on transform and opacity, never a bounce.

**Key Characteristics:**
- Slate canvas, white opaque content surfaces, translucent white only for floating chrome.
- One teal accent for focus, selection and primary actions.
- Layered slate shadows (contact plus ambient) in three steps; never a glow.
- Bricolage Grotesque display, Schibsted Grotesk for everything else including numbers, Sora only for the wordmark.
- Topographic contours over a 192px grid as the page ground on content screens.

## Colors

A cool, nearly monochrome slate palette tinted faintly toward the teal brand hue, with one saturated accent and four darkened status hues.

### Primary
- **Aperture Teal** (brand-teal): the single accent, taken from the Aperture mark. Primary buttons, the focus ring, selected chips, text caret, `accent-color` for native controls. Hover deepens to brand-teal-hover and press to brand-teal-press.
- **Teal Wash** (brand-teal-soft): the background of a selected chip and the text-selection highlight; the only tinted surface.

### Neutral
- **Slate Canvas** (slate-canvas): the page ground on every screen; the token is still named `--space` for legacy reasons and is a colour, not spacing.
- **Paper White** (surface): cards, sheets, controls; content surfaces are always opaque.
- **Sunken Slate** (sunken): segmented-control troughs, idle chips, skeleton loaders.
- **Lifted Slate** (surface-hi): hover state of secondary buttons.
- **Slate Ink** (ink): primary text. **Slate Ink Secondary** (ink-secondary): supporting text, leads. **Slate Ink Tertiary** (ink-tertiary): section labels, placeholders, units; darkened from #64748B so it holds AA on canvas (5.1:1) and sunken (4.8:1).
- **Hairline** / **Hairline Strong**: 1px borders on cards and controls; the strong variant on buttons and chip hover.

### Status
- **Orange**, **Cyan**, **Green**, **Red**: darkened so each holds 4.5:1 on sunken and teal wash. Green and red mark metric deltas up and down.

### Named Rules
**The One Teal Rule.** Teal marks focus, selection and the primary action, and nothing else. Party colours carry identity in the data; teal never doubles as a party colour or a decoration.

**The No Glow Rule.** No galaxy, no glow, no yellow. `--brand-glow` is defined as transparent on purpose, and the override layer hides any `glow` or `halo` class and strips every text shadow.

## Typography

**Display Font:** Bricolage Grotesque (optical sizing on, variable 400–800, falling back to Schibsted Grotesk)
**Body Font:** Schibsted Grotesk (variable 400–800, falling back to the system UI stack)
**Wordmark Font:** Sora 600/700, only in the Starwatch wordmark and the URL beside it

**Character:** A slightly quirky, optically sized display grotesque over a sober newspaper grotesque. The pairing reads editorial rather than dashboard, while the numbers stay in the text face.

### Hierarchy
- **Hero** (720, 60px, 1.06, -.032em): landing headlines; drops to 40px under 760px.
- **Display** (720, 48px, 1.06, -.026em): screen titles; 34px under 760px.
- **Headline** (700, 30px, 1.15) and **Headline small** (650, 24px, 1.2): section heads in the display face. The display steps keep a ~1.25 ratio (24, 30, 38, 48, 60).
- **Title** (650, 20px, -.015em): card and panel titles.
- **Lead** (400, 16px, 1.6, ink-secondary): intro paragraphs.
- **Body** (400, 14.5px, 1.5, -.005em): all running UI text. Small text steps are 13px and 12px; headings are balanced and prose avoids orphans.
- **Label** (550, 13px, sentence case, ink-tertiary): section labels, Linear-style.
- **Numbers**: 650 weight, lining proportional numerals by default ("1.7K" stays compact); tabular numerals only in aligned columns and tables, right-aligned. Units sit at .75em in ink-tertiary.

### Named Rules
**The No Mono Rule.** Data is never set in a monospace face; the `--mono` token deliberately resolves to Schibsted Grotesk.

**The Sentence Case Rule.** Section labels are sentence case at letter-spacing 0, never tracked capitals.

## Layout

A 4pt spacing scale (2, 4, 8, 12, 16, 24, 32, 48, 64, 96px) with semantic aliases: cards pad 16px, panels 24px, stacks 12px, controls 0 12px. The page gutter is 16px and widens to 24px from 768px. Navigation is a floating rail of pills 12px from the top (46px tall), not a full-width bar; the page reserves scroll padding for it. Content screens (By the numbers, Pulse, Spotlight, Radar) lay the topographic contours (`img/bg-topo.svg`, cover, fixed) over a 192px repeating grid (`img/bg-grid.svg`) on the slate canvas; the Atlas map screen is its own ground.

## Elevation & Depth

Hybrid: tonal layering (canvas, sunken, surface) carries most structure, and three layered slate shadows add lift. Each shadow pairs a tight contact shadow with a soft ambient one, all tinted with slate ink (15 23 42), never coloured and never a glow. Floating chrome (navigation pills, popovers) may use restrained translucency, white at 74–90% with a 14–16px blur, hairline edge and a soft shadow; where backdrop-filter is unsupported it falls back to near-opaque white.

### Shadow Vocabulary
- **Resting** (elev-1): cards at rest; the default `--shadow`.
- **Lifted** (elev-2): floating chrome and hover lift.
- **Overlay** (elev-3): popovers, sheets, dialogs.

### Named Rules
**The Opaque Content Rule.** Cards and content stay opaque white; translucency is reserved for chrome that floats over content.

## Shapes

One radius scale with semantic aliases: chips 6px, controls 8px, cards 12px, panels 16px, sheets 20px, navigation pills fully round. Nested radii equal the outer radius minus the padding. Borders are 1px hairlines. A dashed outline is reserved for "not observed" in data marks and for the machine-assigned topic label marker.

## Components

### Buttons
- **Shape:** gently rounded rectangles (control radius), 32px tall, 13px medium text, 0 12px padding.
- **Primary:** teal fill, white text, weight 600, no shadow; hover deepens, press deepens further.
- **Secondary:** white with a strong hairline; hover shifts to lifted slate.
- **Focus:** one 2px teal outline at 2px offset everywhere, keyboard only.

### Chips
- **Style:** 24px tall, chip radius, sunken background, secondary ink, 12px medium text.
- **State:** hover darkens the text and shows a strong hairline; selected is teal wash with teal text and a teal border.

### Segmented control
- **Style:** a sunken trough with a 2px inset; 28px segments at 12.5px/550 in secondary ink; the active segment is white with a 1px slate contact shadow.

### Cards / Containers
- **Corner Style:** card radius (12px).
- **Background:** opaque white with a 1px hairline.
- **Shadow Strategy:** resting elevation; overlays use elev-3.
- **Internal Padding:** 16px cards, 24px panels.

### Navigation
- **Style:** floating translucent pills on an invisible click-through rail: brand pill (mark plus Sora wordmark, snapshot status behind a hairline), the five-screen dock (13.5px/550, secondary ink; hover reveals a scaled slate wash behind the item and the icon sparkle turns), search, and account. The mark turns a quarter on hover. Motion is transform and opacity only.

### Metrics
- **Style:** value 24px/700 in proportional numerals, label 11.5px in secondary ink, delta 11.5px/600 in status green or red.

### Product film (video/src/showreel)
The 45-second film is a motion-design surface in the app's own world: same canvas, ink, one teal, white sheets and display face, but driven by the score. Daniel asked on 13 October 2026 for the pop and action transitions of the Mluva reel in this design, with far fewer screens in a frame, so the film allows what the app UI does not: spring overshoot, motion blur, 3D and full-bleed teal.
- **Ground:** the slate canvas with the app's topographic contours (drawn on from the centre in the opening, lifting on every kick from the drop to the end card) over the 192px grid.
- **Type:** Bricolage Grotesque 720 at -0.036em for every headline and number (112–250px), Schibsted Grotesk 560–640 for labels (44–50px), ink by default, teal for the one thing that matters. Words rise out of their own baseline masks on a spring with vertical motion blur; the opening line rises letter by letter. A teal block wipes in behind the decisive phrase ("attention?", "Not most voted.") and turns it white.
- **Numbers:** odometers in tabular figures count up from zero to the app's exact figure, each digit turning only on a carry, so no figure above the target and no leading zero ever shows.
- **Real pieces:** the welcome wall's tiles and the Spotlight portraits are element screenshots, moved as 3D cards with the app's 20px sheet radius and elev-3; the map flight and the tool pages are per-frame captures on sheets. Nothing is redrawn; the end card discloses "App footage: real captures of the live app".
- **Transitions:** whip pans on one shared curve (`cubic-bezier(.75,0,.25,1)` over 16 frames, fastest on the beat) with directional blur; the mark's blade as the brand wipe; a teal disc from Prague that opens into the flight; a hard cut on the bar; the teal champion card on a slant.
- **End card:** the app's 3D mark slams into the lockup on the final hit with a 12% punch and two contour rings; at rest the lockup is the brand file itself (0 px diff), then the URL in the Sora wordmark face and two Schibsted lines.

## Do's and Don'ts

### Do:
- **Do** put white opaque surfaces on the slate canvas and lift them with elev-1, elev-2 or elev-3 only.
- **Do** keep teal to focus, selection and primary actions (The One Teal Rule).
- **Do** encode colour as party, shape as platform or format, area as the stated metric, and dashed as not observed, the same way on every screen.
- **Do** show attention and votes side by side as separate measures.
- **Do** use proportional numerals by default and tabular numerals only in aligned columns.
- **Do** animate transform and opacity with exponential ease-out (`cubic-bezier(.16,1,.3,1)` or `(.25,1,.5,1)`), and honour reduced motion.
- **Do** show the real app in any film or marketing surface: real captures and element screenshots, moved and masked but never redrawn.

### Don't:
- **Don't** add a galaxy, sky, glow, halo, text shadow or yellow (The No Glow Rule).
- **Don't** make content cards translucent or blurred; translucency is for floating chrome.
- **Don't** set data in a monospace face.
- **Don't** use tracked uppercase for section labels; labels are sentence case.
- **Don't** use bounce or spring overshoot easing in the app UI (the product film is the one exception, above).
- **Don't** merge attention and votes into one score, ranking or combined visual.
