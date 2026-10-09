# Apify inputs

One input file per Apify Actor that Starwatch actually ran during the hackathon. Each file is a valid Actor input you can pass as the run body. Targets are a few public political accounts from the Starwatch snapshot; swap in your own. No tokens, dataset IDs or run IDs are needed to rerun them.

What each Actor was for, the run options (item cap, spending cap, timeout, memory), the output fields Starwatch keeps, observed costs and the failure modes are in [docs/apify-recipes.md](../../docs/apify-recipes.md).

| File | Actor | Run options used in production |
| --- | --- | --- |
| [apify--instagram-profile-scraper.json](apify--instagram-profile-scraper.json) | `apify/instagram-profile-scraper` | one item per profile, cap $0.0023 × profiles + margin |
| [apify--instagram-scraper.json](apify--instagram-scraper.json) | `apify/instagram-scraper` | `maxItems` = accounts × `resultsLimit`, timeout 900 s, 1024 MB |
| [apify--facebook-posts-scraper.json](apify--facebook-posts-scraper.json) | `apify/facebook-posts-scraper` | `maxItems` = pages × `resultsLimit`, timeout 900 s, 1024 MB |
| [apify--google-search-scraper.json](apify--google-search-scraper.json) | `apify/google-search-scraper` | `maxItems` = number of queries, cap at least $0.50, timeout 900 s |
| [clockworks--tiktok-scraper.json](clockworks--tiktok-scraper.json) | `clockworks/tiktok-scraper` | cap at least $0.50, timeout 900 s, 4096 MB |
| [clockworks--tiktok-profile-scraper.json](clockworks--tiktok-profile-scraper.json) | `clockworks/tiktok-profile-scraper` | cap $0.002 × results + margin |
| [streamers--youtube-scraper.json](streamers--youtube-scraper.json) | `streamers/youtube-scraper` | timeout 900 s, 1024 MB |
| [apidojo--twitter-scraper-lite.json](apidojo--twitter-scraper-lite.json) | `apidojo/twitter-scraper-lite` | `maxItems` equal to the input's `maxItems`, 256 MB |
| [apify--website-content-crawler.json](apify--website-content-crawler.json) | `apify/website-content-crawler` | `maxItems` 15, cap $0.10, timeout 75 s, 1024 MB |
