# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

People in Czechia who follow local politics or report on it: journalists, analysts, campaign staff, and voters curious about their own city. They usually arrive from a LinkedIn or social post, often on a phone with the sound off. (From the README and Daniel's requests; not confirmed in an interview.)

## Product Purpose

Starwatch shows what candidates in the 2026 Czech municipal elections in the ten largest cities posted on Instagram, Facebook, TikTok and X, how much attention it got, and, since 11 October 2026, the official result of every candidate next to it. Success is a visitor who looks up their own city and understands attention and votes as separate measures.

## Positioning

Attention is shown next to votes and never merged into a score; every post is attributed only after the account owner was confirmed by an independent public source, and every post links to the original.

## Operating Context

A snapshot of public posts collected 8–9 October 2026, not live monitoring. Czech pre-election rules: no polls, forecasts or scores. Czech professional audience: understatement is valued; self-promotion reads as bragging.

## Capabilities and Constraints

Static app (HTML, CSS, JS with MapLibre and ECharts) at https://starwatch.danielvecera.com, open to everyone with no sign-in, MIT licensed. Screens: Star Atlas, Spotlight, Pulse, Radar, By the numbers, About.

## Brand Commitments

The app's own design system (`app/web/ds.css`): white surfaces on slate canvas `#F2F7F7`, one teal accent `#0E6E6B` for focus and primary actions, layered slate shadows, "no galaxy, no glow". Bricolage Grotesque for display, Schibsted Grotesk for text, Sora for the wordmark. Brand files in `app/web/brand/`, background contours `app/web/img/bg-topo.svg`.

## Evidence on Hand

Real captures of the live app (`video/tmp/captures/`), the snapshot data (`app/web/data/`), official 2026 results from the Czech Statistical Office, the hackathon result at hq.agents007.ai/results (overall winner and Social Media Deep Research topic, 38 projects; no scores published).

## Product Principles

- Show the real app; never redraw it.
- Attention and votes are separate measures, never one score.
- Plain, checkable claims; no bragging.
- Point people to their own city.
