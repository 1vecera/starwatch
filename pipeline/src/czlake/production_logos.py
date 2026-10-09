"""Retained official logos and exact registered-list membership evidence."""
from __future__ import annotations

import csv
import hashlib
import io
import json
import re
import xml.etree.ElementTree as ET
import zipfile
from datetime import datetime
from pathlib import Path
from urllib.parse import unquote_to_bytes, urljoin, urlsplit

from lxml import html

try:
    from .production_images import image_info
except ImportError:
    from production_images import image_info

LOGO_TABLES = ('list_logo', 'list_logo_coverage')
LOGO_DDL = """
CREATE TABLE list_logo(logo_id VARCHAR PRIMARY KEY,entity_id VARCHAR NOT NULL REFERENCES entity(entity_id),brand_id VARCHAR NOT NULL,brand_name VARCHAR NOT NULL,relationship VARCHAR NOT NULL CHECK(relationship IN ('list_brand','registered_party','member_party')),local_path VARCHAR NOT NULL,sha256 VARCHAR NOT NULL,bytes BIGINT NOT NULL,content_type VARCHAR NOT NULL,source_page_url VARCHAR NOT NULL,original_image_url VARCHAR NOT NULL,source_image_pointer VARCHAR NOT NULL,observed_at VARCHAR NOT NULL,reviewer VARCHAR NOT NULL,reviewed_at VARCHAR NOT NULL,source_id VARCHAR NOT NULL REFERENCES source(source_id),source_page_id VARCHAR NOT NULL REFERENCES source(source_id),blob_source_id VARCHAR NOT NULL REFERENCES source(source_id),registry_source_id VARCHAR NOT NULL REFERENCES source(source_id),registry_pointer VARCHAR NOT NULL,membership_evidence VARCHAR NOT NULL);
CREATE TABLE list_logo_coverage(entity_id VARCHAR PRIMARY KEY REFERENCES entity(entity_id),status VARCHAR NOT NULL CHECK(status IN ('downloaded','unknown')),logo_count INTEGER NOT NULL,has_list_brand BOOLEAN NOT NULL,unknown_reason VARCHAR);
"""
LOGO_GATES = {
    'logo_list_grain': "SELECT count(*) FROM list_logo l JOIN entity e USING(entity_id) WHERE e.kind<>'local_list'",
    'logo_coverage_counts': "SELECT count(*) FROM list_logo_coverage c WHERE c.logo_count<>(SELECT count(*) FROM list_logo l WHERE l.entity_id=c.entity_id) OR (c.status='downloaded')<>(c.logo_count>0)",
}


def logo_type(raw):
    """Allow complete raster images and passive SVG; never executable SVG."""
    if len(raw) > 8_000_000:
        raise ValueError('Logo exceeds retained image bound')
    if raw.startswith(b'\x89PNG'):
        if b'IEND' not in raw[-16:]:
            raise ValueError('Incomplete PNG')
    elif raw.startswith(b'\xff\xd8'):
        if not raw.endswith(b'\xff\xd9'):
            raise ValueError('Incomplete JPEG')
    elif raw[:6] in (b'GIF87a', b'GIF89a'):
        if not raw.endswith(b';'):
            raise ValueError('Incomplete GIF')
    elif raw.startswith(b'RIFF'):
        if len(raw) != int.from_bytes(raw[4:8], 'little') + 8:
            raise ValueError('Incomplete WebP')
    else:
        if b'<!ENTITY' in raw.upper() or b'<!DOCTYPE' in raw.upper():
            raise ValueError('SVG declarations are not allowed')
        node = ET.fromstring(raw)
        if node.tag != '{http://www.w3.org/2000/svg}svg':
            raise ValueError('Expected SVG root')
        for element in node.iter():
            tag = element.tag.rsplit('}', 1)[-1].lower()
            if tag in {'script', 'foreignobject', 'iframe', 'object', 'embed'}:
                raise ValueError('Active SVG element')
            for key, value in element.attrib.items():
                name = key.rsplit('}', 1)[-1].lower()
                if name.startswith('on') or (name in {'href', 'base'} and value and not value.startswith('#')):
                    raise ValueError('Active or external SVG attribute')
            styles = ' '.join(element.attrib.values()) + (element.text or '' if tag == 'style' else '')
            if '@import' in styles.casefold() or any(not value.strip(' \"\'').startswith('#') for value in re.findall(r'url\(([^)]+)\)', styles, re.I)):
                raise ValueError('External SVG stylesheet reference')
        return 'image/svg+xml'
    mime, width, height = image_info(raw)
    if min(width, height) < 8 or max(width, height) > 20000:
        raise ValueError('Invalid logo dimensions')
    return mime


def public_https(value):
    p = urlsplit(value)
    return p.scheme == 'https' and bool(p.hostname) and not p.username and not p.password and p.port in (None, 443)


def import_logo_supplement(rows, inputs, path, pin_file):
    document, supplement_id = inputs.read(path)
    if document.get('schema_version') != 'production-official-list-logos-v1':
        raise ValueError('Exact official logo supplement required')
    entities = {row['entity_id']: row for row in rows['entity'] if row['kind'] == 'local_list'}

    def pin(ref):
        p = Path(ref['path']).resolve()
        if not p.is_relative_to(inputs.root):
            raise ValueError('Logo source escaped project evidence root')
        source_id = pin_file(inputs, p, ref['sha256'])
        return p, source_id

    registry, registry_source = pin(document['registry'])
    archive, _ = pin(document['archive'])
    if document['archive'].get('source_url') != 'https://volby.gov.cz/opendata/kv2026/KV2026reg20261007_csv.zip':
        raise ValueError('Unknown official registry release')
    with zipfile.ZipFile(archive) as zipped:
        if zipped.read('csv_od/kvros.csv') != registry.read_bytes():
            raise ValueError('Registry differs from exact official archive')
    registered = {}
    for i, item in enumerate(csv.DictReader(io.StringIO(registry.read_text(encoding='utf-8-sig')))):
        entity_id = 'kv2026:' + item['KODZASTUP'] + ':' + item['OSTRANA']
        if entity_id in entities:
            if entity_id in registered or item['NAZEVCELK'] != entities[entity_id]['name']:
                raise ValueError('Exact registered list grain or name differs')
            registered[entity_id] = (i, item)
    if set(registered) != set(entities):
        raise ValueError('Incomplete registered list scope')
    seen, output = set(), []
    for brand in document['brands']:
        if (brand.get('decision') != 'accept' or brand.get('reviewer') != 'native:/root'
                or not re.fullmatch(r'[a-z0-9_]+', brand.get('brand_id', ''))):
            raise ValueError('Actual coordinator brand/source review required')
        for name in ('reviewed_at', 'observed_at'):
            if datetime.fromisoformat(brand[name]).tzinfo is None:
                raise ValueError('Logo evidence time needs timezone')
        page, page_id = pin(brand['page'])
        image, blob_id = pin(brand['image'])
        if not public_https(brand['source_page_url']) or not public_https(brand['original_image_url']):
            raise ValueError('Official public HTTPS sources required')
        try:
            dom = html.fromstring(page.read_bytes().decode('utf-8-sig'))
        except UnicodeDecodeError:
            dom = html.fromstring(page.read_bytes())
        title = ' '.join(dom.xpath('//title/text()'))
        nodes = dom.xpath(brand['source_image_pointer'])
        if title != brand['source_title'] or len(nodes) != 1:
            raise ValueError('Exact source title/image node differs from brand review')
        raw = image.read_bytes()
        if brand.get('source_encoding') == 'data_uri':
            actual = nodes[0].get('src', '')
            if (nodes[0].tag != 'img' or not actual.startswith('data:image/svg+xml,')
                    or unquote_to_bytes(actual.split(',', 1)[1]) != raw
                    or brand['original_image_url'] != brand['source_page_url']):
                raise ValueError('Embedded logo differs from exact retained data URI')
        elif brand.get('source_encoding') == 'inline_svg':
            start, end = brand['source_byte_range']
            if (type(start) is not int or type(end) is not int or start < 0 or end <= start
                    or page.read_bytes()[start:end] != raw or nodes[0].tag != 'svg'
                    or html.tostring(html.fromstring(raw), with_tail=False) != html.tostring(nodes[0], with_tail=False)
                    or brand['original_image_url'] != brand['source_page_url']):
                raise ValueError('Inline logo differs from retained SVG node and exact raw byte span')
        else:
            actual = urljoin(brand['source_page_url'], nodes[0].get(brand['source_attribute'], ''))
            if (nodes[0].tag != 'img' or actual != brand['original_image_url']
                    or brand['source_attribute'] not in {'src', 'data-src', 'data-lazy-src'}):
                raise ValueError('Logo URL differs from retained exact source field')
        mime = logo_type(raw)
        if mime != brand['content_type']:
            raise ValueError('Logo MIME differs from retained bytes')
        for link in brand['lists']:
            entity_id = link['entity_id']
            if entity_id not in registered or (entity_id, brand['brand_id']) in seen:
                raise ValueError('Unknown or duplicate logo/list relation')
            seen.add((entity_id, brand['brand_id']))
            i, registered_row = registered[entity_id]
            if link['list_name'] != registered_row['NAZEVCELK']:
                raise ValueError('Logo link does not name exact registered list')
            relationship = link['relationship']
            composition = {str(int(value)) for value in registered_row['SLOZENI'].split(',')}
            party = brand.get('registered_party_code')
            if party:
                if party not in composition or relationship != ('registered_party' if composition == {party} else 'member_party'):
                    raise ValueError('Logo party membership differs from official composition')
                evidence = {'registered_party_code': party, 'composition': sorted(composition), 'basis': 'exact_official_registered_composition'}
            else:
                needle = link.get('exact_name_component', '')
                if not needle or needle not in registered_row['NAZEVCELK'] or relationship not in {'list_brand', 'member_party'}:
                    raise ValueError('Explicit reviewed local-list name component required')
                evidence = {'exact_name_component': needle, 'list_name': registered_row['NAZEVCELK'], 'basis': 'exact_registered_name_and_reviewed_official_brand_source'}
            output.append({'logo_id': 'logo:' + hashlib.sha256((entity_id+'|'+brand['brand_id']).encode()).hexdigest()[:24],
                           'entity_id': entity_id, 'brand_id': brand['brand_id'], 'brand_name': brand['brand_name'], 'relationship': relationship,
                           'local_path': str(image), 'sha256': brand['image']['sha256'], 'bytes': len(raw), 'content_type': mime,
                           'source_page_url': brand['source_page_url'], 'original_image_url': brand['original_image_url'],
                           'source_image_pointer': brand['source_image_pointer'], 'observed_at': brand['observed_at'],
                           'reviewer': brand['reviewer'], 'reviewed_at': brand['reviewed_at'], 'source_id': supplement_id,
                           'source_page_id': page_id, 'blob_source_id': blob_id, 'registry_source_id': registry_source,
                           'registry_pointer': '/csv_od/kvros.csv/records/' + str(i), 'membership_evidence': json.dumps(evidence, ensure_ascii=False, sort_keys=True)})
    rows['list_logo'] = output
    rows['list_logo_coverage'] = []
    for entity_id in sorted(entities):
        logos = [item for item in output if item['entity_id'] == entity_id]
        rows['list_logo_coverage'].append({'entity_id': entity_id, 'status': 'downloaded' if logos else 'unknown', 'logo_count': len(logos),
                                           'has_list_brand': any(item['relationship'] in {'list_brand', 'registered_party'} for item in logos),
                                           'unknown_reason': None if logos else 'no_reviewed_official_logo_retained'})
