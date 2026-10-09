"""Write web/data/stats.js: headline collection totals from the pinned production checkpoint manifest (read-only)."""
import json, pathlib, datetime
ROOT = pathlib.Path('/home/vecera/code/agents007-hackathon/tmp/production/read')
cur = json.loads((ROOT / 'current.json').read_text())
man = json.loads((ROOT / cur['manifest']).read_text())
c = man.get('counts', {})
pick = lambda k: c.get(k)
stats = {
    'checkpoint_id': cur['checkpoint_id'], 'created_at': cur.get('created_at'),
    'exported_at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
    'collected_posts': pick('asset'), 'verified_posts': pick('verified_assets'),
    'metric_values': pick('metric'), 'media_files': pick('media_resource'), 'sources': pick('source'),
    'accounts_discovered': pick('account'), 'verified_accounts': pick('verified_accounts'),
    'registered_entities': pick('entity'), 'cities': pick('area'), 'reviewed_statements': pick('claim'),
    'topics': pick('topic'), 'web_pages': pick('web_asset'), 'publishers': pick('publisher'),
    'portrait_coverage_entities': pick('entity_photo_coverage'), 'quarantined_records': pick('quarantine'),
    'production_observations': pick('production_observation'),
    'coverage_notes': man.get('coverage', {}), 'privacy': man.get('privacy'),
}
out = pathlib.Path(__file__).resolve().parent.parent / 'web' / 'data' / 'stats.js'
out.write_text('/* Collection totals from the production checkpoint manifest. Generated; local only. */\nwindow.SW_STATS=' + json.dumps(stats, ensure_ascii=False) + ';\n')
print(json.dumps({k: stats[k] for k in ('checkpoint_id', 'collected_posts', 'verified_posts', 'metric_values', 'media_files', 'sources')}))
