# Privacy and ethics

Starwatch looks at what public candidates publish in public. It does not look at the people who read, like or comment on it.

## Public sources only

- Every post comes from a public account that is independently tied to a registered candidate or a registered party list in one of ten Czech city councils. Private profiles are recorded as private and not collected.
- No private groups, private messages, login-only pages, leaked material, fake accounts or CAPTCHA bypass.
- Collection keeps an allowlist of public post and profile fields. Comments, commenter and liker identities, follower lists, tagged users and mentions are dropped before anything is written to disk.
- No face recognition. A photo is attributed to a person only when its source names that person or it is the avatar of the person's own verified account.

## No voter profiling, no persuasion

- Starwatch builds no profiles of voters, commenters or audiences and joins no identities across platforms for them.
- It does not infer political opinions, religion, health, ethnicity or any other sensitive trait, and it does not score anyone's character or trustworthiness.
- Metrics are dated observations of public counts. They are not measures of support, and the app says so.
- Starwatch gives no campaign advice: no recommendations of topics, messages or timing, and no tactics against opponents. The drafting workspace from the hackathon (Studio) was removed before launch.

## Election silence

Czech law (§ 30(2) of Act No. 491/2001 Coll., on elections to municipal councils) bans publishing the results of pre-election and election polls from 7 October 2026 until voting ends on Saturday 10 October 2026 at 14:00. During the hackathon night some published polls, seat projections and betting odds were collected for the ten cities. All of them were removed from the snapshot before launch, and Starwatch will not publish poll, forecast or betting data. 2026 election results are added only after the polls close.

## A snapshot, behind sign-in

The app shows public posts collected on 8–9 October 2026. It is not live monitoring. The collected snapshot (posts, images, videos and the exported data file) is not in the public Git repository. It is served only to signed-in visitors (GitHub, Google or Facebook sign-in), with no-index and no-store headers, and every post links to its original on the platform. The welcome page is public.

## Data retention

The raw provider datasets from the scraping run, and the raw landings of every other source, are deleted after the launch, both locally and from the Apify account's storage. What remains is the reviewed snapshot the app serves: allowlisted metadata, dated metrics, reviewed statements and the media of admitted posts. When a post is deleted at its source, the snapshot still reflects 9 October; a correction request (below) removes it.

## Corrections and removal

If you are a candidate, or represent a party list, and something in Starwatch is wrong, please [open an issue on GitHub](https://github.com/1vecera/starwatch/issues). Useful things to include:

- The page or the original post URL.
- What is wrong: a wrong account match, a post that is not yours, an incorrect photo, a wrong 2022 result, a statement or topic label, or a post you have deleted.
- A public link that shows the correct information, for example your official candidate page.

Do not post private information in the issue; it is public. Wrong account matches, wrong photos and deleted posts are removed from the snapshot. You can also reach me on [LinkedIn](https://www.linkedin.com/in/1vecera/) or [X](https://x.com/1vecera).

Daniel Večeřa, Prague
