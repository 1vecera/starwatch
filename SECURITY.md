# Security policy

## Reporting a vulnerability

Please report security problems privately through GitHub: open the repository's **Security** tab and choose **Report a vulnerability** ([direct link](https://github.com/1vecera/starwatch/security/advisories/new)). Do not open a public issue for anything that could be exploited, such as a way around sign-in, a leaked credential or access to the collected snapshot without a session.

If private reporting is unavailable, open a [public issue](https://github.com/1vecera/starwatch/issues) that only asks for a private contact, without details, or message Daniel Večeřa on [LinkedIn](https://www.linkedin.com/in/1vecera/) or [X](https://x.com/1vecera).

Please include what you found, how to reproduce it and what an attacker could reach. This is a non-commercial project with a single maintainer: reports are answered as soon as possible, and there is no bug bounty.

## Scope

- The live site at <https://starwatch.agenticanalytics.cz>: the Cloudflare sign-in Worker (`/login`, `/auth/*`), the CloudFront gate in front of the app, and the static app itself.
- The code on the `main` branch: `app/`, `pipeline/` and `deploy/`.

The `archive/` directory and the `hackathon-freeze` tag are historical and not maintained; report issues there only if they affect the live site or `main`.

## How the project handles secrets and data

- Credentials (Apify, OAuth clients, session keys) live in environment variables or the hosting providers' secret stores. They are never committed; placeholders in `deploy/` are filled at deploy time.
- The collected snapshot (posts, images, videos and the exported data file) is kept out of Git and served only to signed-in visitors.
- The local servers in `app/` and `pipeline/` bind to `127.0.0.1` and are meant for development, not public deployment.

Requests about personal data shown in the app (corrections or removal) are not security issues; see [CONTRIBUTING.md](CONTRIBUTING.md#corrections-and-removal-requests).
