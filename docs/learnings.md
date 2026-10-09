# Learnings

What I would tell myself before the next night like this. Each point comes from something that happened while building Starwatch on 8–9 October 2026; [the story](story.md) has the context.

## Apify and collection

- **Always pass `maxItems` and `maxTotalChargeUsd` as run options**, not only input fields. Apify enforces run options even when an input field is wrong.
- **Check each Actor's minimum spending cap.** `clockworks/tiktok-scraper` and `apify/google-search-scraper` refuse a `maxTotalChargeUsd` below $0.50; a lower cap fails the run with a 400. Keep the cap at the minimum and control cost with `maxItems`.
- **Request only the fields you need** with `fields=` on every dataset read. The Facebook and Instagram Actors return comment previews by default, which means other people's data on your disk. In production, filter every item through a per-Actor allowlist before writing it.
- **Turn every paid add-on off explicitly.** Google search has AI overview, AI mode, Gemini, Perplexity, ChatGPT, Copilot, leads and website add-ons; TikTok and YouTube have downloads, transcripts and AI summaries. Validate that the input disables them before the run starts.
- **Download media at collection time.** Instagram and TikTok media URLs are signed and expire, and Instagram blocks hotlinking. Record size, MIME type and hash for every file.
- **Fetch TikTok caption tracks immediately.** The `subtitleLinks` in TikTok results include TikTok's own Czech ASR track with timecodes, free, but the links expire within hours. 33 of the first 40 videos had one.
- **Do not use add-ons that block streaming when you need speed.** With TikTok's video download on, the first item arrived after about 80 seconds instead of 15. Stream posts without it and fetch the few videos you need in a second run by URL.
- **Split deep-history batches** so they finish inside the timeout. Two 400-post Instagram batches of ten accounts ran past 900 seconds; they kept their 6,212 posts, but a timeout is not a plan.
- **Read cost from the run after it ends, twice.** Apify updates `usageTotalUsd` and charged event counts a few seconds after a run stops, and replies can lag. Settle from the charged event counts and keep positive counts when a later reply is missing them.
- **Cap slow lanes and keep partial results.** A slow website crawl held a live run for 146 seconds; the lane now stops at 75 seconds and keeps what arrived.
- **Prefer a direct request for small reads.** Reading an anchor website directly takes about 0.3 seconds; use the crawler only when the site refuses a direct client.
- **Rate limits are real on free sources.** The Wikidata query service was limited to one request per minute that night, and Wikimedia Commons returned 429 for logo downloads. Run them as background jobs with patient retries and honour the cooldown.

## Identity and data

- **Ownership needs an independent anchor.** Admit an account only when an independent source (the candidate's own site, the party's candidate page, a city roster) links that exact handle, the public profile matches and the person holds a current candidacy or reviewed local role. A name, bio, verified badge or search hit is a lead.
- **Collection yield is not authorship.** In the first Facebook proof, four of five posts returned for a requested page had another author. Admit a post only when its own author field matches the reviewed account; for Facebook, bind the page's vanity URL to its numeric ID first.
- **Anchors link institutional accounts.** A politician's site linked a government YouTube channel. Compare the linked account's display name with the person before accepting it.
- **Namesakes are normal.** A former prime minister and a senator share a name; three candidates in one city share another. Keep inferred person clusters as review flags and never merge on name alone.
- **Old anchors rot.** One campaign domain now redirects to betting content. Re-check an anchor's final URL before trusting it.
- **Keep unknown as unknown.** Provider values like `-1` become null with a reason, and the UI shows a dash, not zero. Missing coverage must look different from zero activity.
- **Keep relations separate.** Owning an account, publishing a post, being mentioned, being pictured and being quoted are five different facts with different evidence.
- **Know what an official number means before you label it.** Czech municipal candidate vote totals include whole-list votes, so they are not personal preference votes; the official adjusted list percentage is not the raw vote share.
- **Match history conservatively.** Link a 2026 candidate to 2022 only on exact name, same city, overlapping birth windows from official ages and a unique match in both directions. Ballot numbers and member overlap do not carry a coalition's result.
- **Separate qualification from ranking.** A max/OR rule (one strong signal qualifies, signals are not summed, unknown is not zero) kept newcomers in. Review the output by eye: "first on the list" turned out to be a loophole and was removed as a qualifying signal.
- **Let integrity gates refuse a release.** The last checkpoint of the night was refused by its own label-source gate, and the app kept the previous good snapshot. That is the gate doing its job.

## Cost control

- **Size from real bills, not from list prices.** An early estimate said a broad sample would cost $88 in Facebook posts. Reading actual run bills showed that one Instagram profile request returns a follower count and about twelve recent posts for $0.0023, which changed the whole plan.
- **Filter dates locally when it is cheaper.** Facebook's date filter adds 25% per post and TikTok's adds 50% per result. For recent samples, take the latest N and filter yourself.
- **Reserve the full cap before every run.** Count in-flight runs at their spending cap, not their expected cost, behind a file lock. The exploration lane could not pass its $20 cap even with several agents launching runs.
- **Never retry an ambiguous start blindly.** Record a durable start boundary before the request. If the start fails after that, keep the reservation until you can match the exact run ID. One Google start ended this way and its $0.08 stayed reserved to the end.
- **Pin price and schema with every batch.** A manifest with the exact input hash, a price snapshot, the expected upper cost and the provider cap makes every batch reviewable before and after it runs.
- **Pause and audit when the plan changes.** When I paused collection, two discovery runs were still going. They were aborted cleanly and their delivered pages recovered read-only instead of being bought again.
- **Price everything, or say it is unpriced.** Apify costs were settled to the cent; Exa, Scribe and model calls were reserved as conservative provisions, and agent subscriptions were not priced. Say which is which.

## Agent orchestration

- **One head of staff, many workers, one task list.** The head of staff keeps decisions and the canonical `TODO.md`; workers get a written brief, their own Git worktree and a report file. Nobody else edits the task list.
- **Workers never wait.** Milestone times are deadlines, not pace. Reports go to files while work continues; a question does not stop work. Briefs that say "stop and report" produce idle agents.
- **Turn off unsolicited pings.** Reports and a shared board are enough; interruptions cost more than they deliver.
- **Make the persona opt-in.** A project settings file made every Claude session start as head of staff, workers included. Start roles explicitly per session.
- **Be ready to switch runtimes.** When the Claude session hit its usage limit at 00:25, the same head-of-staff instructions moved to a Codex profile in minutes, and Claude was kept for the final screens.
- **One writer per shared resource.** In the production run one coordinator owned the ledger, paid starts and checkpoint writes; workers wrote only to isolated folders. A coordinator handover then lost nothing.
- **Independent review means a different agent.** Classification and its review ran in separately registered sessions, and the review was bound to the exact label hash it checked.
- **Notify once, then stop.** A readiness timer that checks every two minutes and sends exactly one notification to the app-building session, then disables itself, beats a polling agent.
- **Watch for self-inflicted process kills.** `pkill -f starwatch` killed the agent's own shell because its working directory contained "starwatch". Kill by PID.
- **Pass the project path to background jobs.** A background `uv run` started from another directory lost its project and repeated a paid run.
- **Record provenance of decisions.** An agent's runtime constraint is not the user's decision. The board recorded who decided what.

## Design

- **Throw away the wrong direction early.** The first Figma concepts and the dark galaxy look both went; the light, schematic Atlas C survived because it put evidence first.
- **Run an anti-slop gate.** The [Impeccable](https://github.com/pbakaus/impeccable) detector, `npx -y impeccable@4.1.0 detect <url> --json`, caught gradient text, glows, cards in cards and hero-metric rows. Fix each finding or state why it is intentional.
- **Check contrast on translucent panels.** Secondary captions on 78%-opaque panels measured 2.5–3.2:1. Text-heavy panels need a near-opaque surface.
- **Do not fake features.** Google, Microsoft and SAML buttons on a demo with no real sign-in read as boilerplate and claim integrations that do not exist.
- **Reserve layout while loading.** Skeleton placeholders and image fade-in instead of blank areas that pop in.
- **Use real content in the opener.** The stage opener that worked was a wall of real collected posts, not a generated animation.

## Product honesty

- **Label the mode.** Live, cached, sample and simulated are different; the public app says it is a snapshot of 8–9 October 2026.
- **Show coverage next to every comparison.** State the window, the denominator and what is missing.
- **Respect election silence.** Czech law bans publishing poll results in the final days before the vote. Polls and betting odds collected during the night were removed before launch.
- **Keep data out of Git.** Publish code, recipes and docs; serve collected content only behind sign-in, link to originals and delete the raw scrape after launch.

## Hosting

- **Know the email limits before choosing email codes.** Amazon Cognito's built-in sender allows 50 emails per day per AWS account. Social sign-in avoids the problem and the password handling.
- **Gate the origin, not only the page.** Keep the bucket private, let only the CDN read it, and let the CDN serve anything other than the public landing page only to requests that came through the sign-in edge.
- **Preserve byte ranges end to end.** Video seeking breaks when any proxy drops range requests; test seeking through the full chain.
