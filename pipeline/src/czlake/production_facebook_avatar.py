"""Admit explicit Facebook author account imagery from already reviewed owners.

No URL guessing, network retrieval, profile-visibility claim or depicted-person
identification. Shared image code retains the byte/hash/type/dimension checks.
"""
from __future__ import annotations
import re
from urllib.parse import urlparse

OWNER_REASONS = {
    'independently_reviewed_exact_page_and_numeric_id',
    'independently_reviewed_official_vanity_metadata_numeric_bridge',
}


def numeric_profile(value):
    if not isinstance(value, str):
        return None
    parsed = urlparse(value)
    if (parsed.scheme != 'https' or parsed.hostname not in {'facebook.com', 'www.facebook.com'}
            or parsed.username or parsed.password or parsed.port not in (None, 443)
            or parsed.query or parsed.fragment):
        return None
    path = parsed.path.strip('/')
    return path if re.fullmatch(r'[1-9][0-9]*', path) else None


def require_facebook_avatar(rows, inputs, source, item, target, page_url, pin, pointer_value):
    match = re.fullmatch(r'facebook:([1-9][0-9]*)', str(item.get('account_id', '')))
    if not match:
        raise ValueError('Facebook avatar requires exact numeric account ID')
    page_id = match.group(1)
    account = next((r for r in rows['account'] if r['account_id'] == item['account_id']), None)
    if (not account or account.get('platform') != 'facebook' or account.get('handle') != page_id
            or account.get('identity_status') != 'confirmed'):
        raise ValueError('Facebook avatar requires independently owned admitted account')
    source_pointer = item.get('source_image_pointer')
    point = re.fullmatch(r'(/items/(?:0|[1-9][0-9]*))/user/profilePic', source_pointer or '')
    if (source.get('schema_version') != 1 or source.get('policy_version') != 'public-metadata-v1'
            or source.get('actor') != 'apify/facebook-posts-scraper' or not point):
        raise ValueError('Facebook avatar requires exact public post-author image pointer')
    record = pointer_value(source, point.group(1))
    author = record.get('user') if isinstance(record, dict) else None
    if (not isinstance(author, dict) or type(author.get('id')) is not str
            or author['id'] != page_id or numeric_profile(author.get('profileUrl')) != page_id
            or page_url != author.get('profileUrl')
            or item['source_page'].get('text_pointer') != point.group(1) + '/user/name'
            or not isinstance(author.get('name'), str)
            or author.get('profilePic') != item.get('original_image_url')):
        raise ValueError('Facebook avatar source author/profile must match exact owner')
    owners = set()
    for key in ('user', 'owner', 'author'):
        candidate = record.get(key)
        if isinstance(candidate, dict) and (candidate.get('id') is not None or candidate.get('username') is not None):
            owners.add(candidate.get('id') if candidate.get('id') is not None else candidate.get('username'))
    if record.get('userId') is not None:
        owners.add(record['userId'])
    top = urlparse(record.get('topLevelUrl', ''))
    if (owners != {page_id} or top.scheme != 'https'
            or top.hostname not in {'facebook.com', 'www.facebook.com'}
            or top.username or top.password or top.query or top.fragment
            or re.fullmatch('/' + re.escape(page_id) + r'/posts/[A-Za-z0-9]+/?', top.path) is None
            or not isinstance(record.get('postId'), str) or not record['postId']):
        raise ValueError('Facebook avatar author/container disagreement remains held')
    # Bind the specific independent proof to the account relation already admitted
    # in this graph; a copied review or an unknown/conflicted graph owner cannot pass.
    evidence = item.get('identity_evidence', {})
    reference = evidence.get('reviewed_owner_proof')
    review_path, review_id = pin(reference)
    review, loaded = inputs.read(review_path)
    proof = pointer_value(review, reference.get('pointer'))
    admitted = any(
        r['account_id'] == item['account_id'] and r['entity_id'] == target['entity_id']
        and r['status'] == 'confirmed' and r.get('reason') in OWNER_REASONS
        and r.get('source_id') == review_id and r.get('source_pointer') == reference.get('pointer')
        for r in rows['account_relation']
    )
    if (not admitted or loaded != review_id or not isinstance(proof, dict)
            or reference.get('pointer') != '/candidates/' + target['entity_id']
            or proof.get('platform') != 'facebook' or proof.get('page_id') != page_id
            or numeric_profile(proof.get('profile_url')) != page_id
            or proof.get('adjudication') != 'confirmed' or proof.get('identity_confirmed') is not True
            or proof.get('page_id_link_confirmed') is not True):
        raise ValueError('Facebook avatar needs exact independently owned account proof source')
    download = item.get('download')
    if isinstance(download, dict):
        image = urlparse(item['original_image_url'])
        final = urlparse(download.get('final_url', ''))
        if (download.get('original_url') != item['original_image_url'] or image.scheme != 'https'
                or not image.hostname or image.username or image.password
                or final.scheme != 'https' or not final.hostname or final.username or final.password):
            raise ValueError('Facebook avatar download must retain exact public original image URL')
