# `window.SW_RAW` — app input format

`tools/export_real.py` writes `web/data/real.js` as one classic script: `window.SW_RAW = {...};`. `web/sw.js` turns it (or the simulated universe when it is absent or `?data=sim`) into `window.SW`, which every screen reads. Plain JSON values; `null` means unknown, never zero.

```js
window.SW_RAW = {
  source: {kind: "real", checkpoint_id, created_at, schema_version, exported_at},
  cities: [{id, name, lon, lat, population, valid_candidacies, retained_lists}],
  lists:  [{id, city_id, name, short, number, size, relevant}],          // size = valid candidacies on the list
  cands:  [{id, name, list_id, city_id, position, qualified, age, occupation}],
  accounts: [{id, entity_id, platform, handle, url, followers, followers_observed_at}],
  assets: [{id, account_id, owner_entity_id, platform, type, published_at, text, url,
            image,                 // local path under web/media/ or null
            views, likes, comments, shares, observed_at,
            relations: [{kind: "about" | "mentions" | "depicts", entity_id}],
            topics: [topic_id], topic_status,   // "admitted" | "reviewed_pending_promotion" | null
            claims: [{text, quote, start_s, end_s, status}]}],
  topics: [{id, label, status}],
  coverage: [ /* coverage.json rows */ ]
};
```

- `platform`: `instagram | facebook | tiktok | youtube | x | news | web`.
- `type`: `post | video | reel | article | page`.
- `owner_entity_id` is a candidate id or a list id, only from independently verified ownership.
