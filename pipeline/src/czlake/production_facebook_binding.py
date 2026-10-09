"""Narrow reviewed official vanity -> observed public profile -> numeric bridge.

No network or URL/name inference is performed here. Every chain input is pinned,
and per-post author/container disagreement remains a separate ingest guard.
"""
from __future__ import annotations
import json
import re
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlparse, parse_qs, unquote

KIND = 'official_vanity_public_metadata_numeric'
SCHEMA = 'production-fb-public-profile-metadata-v1'
PROPOSER = 'native:/root/facebook_binding'


class ExactElement(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.elements = []

    def handle_starttag(self, tag, attrs):
        self.elements.append((tag, dict(attrs)))


def exact_metadata(field):
    try:
        parser = ExactElement()
        parser.feed(field.get('exact_element', ''))
        attribute = field.get('attribute')
        for tag, attrs in parser.elements:
            if attribute == 'canonical' and tag == 'link' and attrs.get('rel') == 'canonical':
                return attrs.get('href') == field.get('content')
            if tag == 'meta' and attrs.get('property') == attribute:
                return attrs.get('content') == field.get('content')
    except (TypeError, ValueError):
        pass
    return False


def exact_header(header, page_id):
    try:
        raw = json.loads('{' + header['exact_json'] + '}')
        variables = raw['variables']
        return (raw['queryName'] == header.get('queryName') == 'ProfileCometHeaderQuery'
                and variables['selectedID'] == header.get('selectedID') == page_id
                and variables['userID'] == header.get('userID') == page_id)
    except (KeyError, TypeError, ValueError):
        return False


def profile_key(value):
    if not isinstance(value, str):
        return None
    p = urlparse(value)
    if p.scheme not in {'http', 'https'} or p.hostname not in {'facebook.com', 'www.facebook.com'} or p.username or p.password or p.fragment:
        return None
    path = unquote(p.path).strip('/')
    if path == 'profile.php':
        values = parse_qs(p.query).get('id', [])
        return values[0] if len(values) == 1 and values[0].isdigit() else None
    if not path or '/' in path:
        return None
    # Harmless locale is not identity-bearing; all other query keys fail closed.
    if any(k not in {'locale'} for k in parse_qs(p.query)):
        return None
    return path.casefold()


def pointer(document, value):
    if not isinstance(value, str) or not value.startswith('/'):
        raise ValueError('Exact bridge source pointer required')
    for part in value[1:].split('/'):
        part = part.replace('~1', '/').replace('~0', '~')
        document = document[int(part)] if isinstance(document, list) else document[part]
    return document


def load_pinned(inputs, path, expected, pin_file):
    chosen = Path(path)
    chosen = chosen if chosen.is_absolute() else inputs.root / chosen
    chosen = chosen.resolve()
    cached = inputs.sources.get(chosen)
    if chosen in inputs.values and cached:
        if cached['sha256'] != expected:
            raise ValueError('Pinned bridge input hash disagrees with prior read')
        pinned = cached['source_id']
    else:
        pinned = pin_file(inputs, chosen, expected)
    # Inputs.unchanged() at export rechecks physical bytes after cached reads.
    document, loaded = inputs.read(chosen)
    if pinned != loaded or not isinstance(document, dict):
        raise ValueError('Pinned bridge input malformed or changed')
    return document


def fresh(value, as_of):
    try:
        date = datetime.fromisoformat(value)
        end = datetime.fromisoformat(as_of)
        return date.tzinfo is not None and 0 <= (end - date).total_seconds() <= 30 * 86400
    except (TypeError, ValueError):
        return False


def confirmed_facebook_binding(inputs, proof, entity_id, as_of, pin_file, reviewer_identity):
    binding = proof.get('facebook_binding')
    if not isinstance(binding, dict) or binding.get('kind') != KIND:
        return False
    reviewer = binding.get('independent_reviewer')
    proposer = binding.get('proposer')
    native_identity = r'native:/root(?:/[a-z0-9_]+)*'
    if not isinstance(proposer, str) or not re.fullmatch(native_identity, proposer):
        return False
    if not isinstance(reviewer, str) or not re.fullmatch(native_identity, reviewer) or reviewer == proposer or reviewer != reviewer_identity or proof.get('reviewer_identity') != reviewer:
        return False
    if binding.get('status') != 'accepted' or not fresh(binding.get('reviewed_at'), as_of):
        return False
    evidence = load_pinned(inputs, binding['evidence_path'], binding['evidence_sha256'], pin_file)
    if evidence.get('schema_version') != SCHEMA or evidence.get('entity_id') != entity_id or evidence.get('http_status') != 200 or evidence.get('response_truncated') is not False or not fresh(evidence.get('observed_at'), as_of):
        return False
    if not re.fullmatch(r'[0-9a-f]{64}', str(evidence.get('raw_sha256', ''))):
        return False
    page_id = proof.get('page_id')
    vanity = profile_key(proof.get('exact_href'))
    if not isinstance(page_id, str) or not page_id.isdigit() or not vanity or vanity.isdigit() or vanity.startswith('pfbid'):
        return False
    if profile_key(proof.get('profile_url')) != page_id or evidence.get('numeric_page_id') != page_id:
        return False
    if any(profile_key(evidence.get(key)) != vanity for key in ('source_url', 'final_url', 'reviewed_owner_url')):
        return False
    metadata = evidence.get('metadata', [])
    canonical = [m for m in metadata if m.get('attribute') in {'canonical', 'og:url'}]
    if {m.get('attribute') for m in canonical} != {'canonical', 'og:url'} or any(profile_key(m.get('content')) != vanity or not exact_metadata(m) or not m.get('xpath') for m in canonical):
        return False
    app_ids = set()
    for m in metadata:
        if m.get('attribute') in {'al:android:url', 'al:ios:url'}:
            match = re.fullmatch(r'fb://profile/(\d+)/?', str(m.get('content', '')))
            if match:
                if not exact_metadata(m) or not m.get('xpath'):
                    return False
                app_ids.add(match.group(1))
    if app_ids != {page_id}:
        return False
    headers = evidence.get('profile_header_queries', [])
    if not headers or not all(exact_header(h, page_id) for h in headers):
        return False
    # The original independently reviewed official ownership proof is preserved.
    original = load_pinned(inputs, binding.get('prior_review_snapshot_path') or evidence['reviewed_proof_path'], evidence['reviewed_proof_sha256'], pin_file)
    prior = pointer(original, evidence['reviewed_proof_pointer'])
    prior_reviewer = prior.get('reviewer_identity') or prior.get('reviewer') or original.get('reviewer_identity') or original.get('reviewer')
    if not prior_reviewer or prior_reviewer == proposer or prior.get('entity_id') != entity_id or prior.get('platform') != 'facebook' or profile_key(prior.get('profile_url') or prior.get('url')) != vanity:
        return False
    if prior.get('decision') not in {'accepted', 'anchor_confirmed_not_admitted'} or prior.get('adjudication') not in {'confirmed_owner_url_only', 'confirmed_vanity_url'}:
        return False
    source = urlparse(prior.get('source_url', ''))
    if source.scheme not in {'http', 'https'} or not source.hostname or source.hostname in {'facebook.com', 'www.facebook.com', 'instagram.com', 'www.instagram.com'} or source.username or source.password:
        return False
    if proof.get('source_url') != prior.get('source_url') or not fresh(prior.get('observed_at'), as_of):
        return False
    official = load_pinned(inputs, prior['evidence_path'], prior['evidence_sha256'], pin_file)
    if official.get('source_url') != prior.get('source_url'):
        return False
    links = official.get('structural_links', []) + official.get('links', [])
    if official.get('exact_href') is not None:
        links.append({'exact_href': official['exact_href']})
    if not any(profile_key(link.get('exact_href')) == vanity for link in links):
        return False
    # Require actual observed provider author URL/ID, never inputUrl or pageName.
    agreeing = False
    for observation in evidence.get('provider_observations', []):
        raw = load_pinned(inputs, observation['raw_path'], observation['raw_sha256'], pin_file)
        if raw.get('actor') != 'apify/facebook-posts-scraper':
            continue
        row = pointer(raw, observation['source_pointer'])
        author = row.get('user')
        if not isinstance(author, dict):
            continue
        owners = {str(row.get(k, {}).get('id') or row.get(k, {}).get('username')) for k in ('user', 'owner', 'author') if isinstance(row.get(k), dict) and (row[k].get('id') or row[k].get('username'))}
        if row.get('userId') is not None:
            owners.add(str(row['userId']))
        top_id = urlparse(row.get('topLevelUrl', '')).path.strip('/').split('/')[0]
        if owners == {page_id} and str(author.get('id')) == page_id and profile_key(author.get('profileUrl')) == page_id and top_id == page_id and observation.get('author_id') == page_id and observation.get('author_profile_url') == author.get('profileUrl'):
            agreeing = True
    return agreeing
