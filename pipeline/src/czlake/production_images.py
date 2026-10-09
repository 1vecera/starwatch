"""Explicit source image metadata and target gaps, without depicted identity inference."""

from __future__ import annotations

import re
import struct
import unicodedata
from pathlib import Path
from urllib.parse import parse_qs, urljoin, urlparse

from lxml import html

try:
    from .production_facebook_avatar import require_facebook_avatar
    from .production_web import public_url, serialized, timestamp
except ImportError:
    from production_facebook_avatar import require_facebook_avatar
    from production_web import public_url, serialized, timestamp

IMAGE_TABLES = ("source_image", "entity_photo_coverage")
IMAGE_DDL = """
CREATE TABLE source_image(image_id VARCHAR PRIMARY KEY,entity_id VARCHAR NOT NULL REFERENCES entity(entity_id),target_id VARCHAR NOT NULL,kind VARCHAR NOT NULL CHECK(kind IN ('source_bound_portrait','owned_account_avatar')),relation_status VARCHAR NOT NULL CHECK(relation_status IN ('source_identified','unknown')),depicted_person_status VARCHAR NOT NULL CHECK(depicted_person_status='unknown'),download_status VARCHAR NOT NULL CHECK(download_status IN ('downloaded','failed','source_only')),local_path VARCHAR,sha256 VARCHAR,bytes BIGINT,content_type VARCHAR,width INTEGER,height INTEGER,original_image_url VARCHAR NOT NULL,observed_at VARCHAR NOT NULL,source_page_url VARCHAR NOT NULL,source_page_sha256 VARCHAR NOT NULL,source_image_pointer VARCHAR NOT NULL,source_text_pointer VARCHAR NOT NULL,identity_evidence VARCHAR NOT NULL,account_id VARCHAR REFERENCES account(account_id),failure_reason VARCHAR,source_id VARCHAR NOT NULL REFERENCES source(source_id),source_page_id VARCHAR NOT NULL REFERENCES source(source_id),blob_source_id VARCHAR REFERENCES source(source_id),source_pointer VARCHAR NOT NULL,CHECK((download_status='downloaded')=(local_path IS NOT NULL)));
CREATE TABLE entity_photo_coverage(entity_id VARCHAR PRIMARY KEY REFERENCES entity(entity_id),target_id VARCHAR NOT NULL UNIQUE,name VARCHAR NOT NULL,city VARCHAR NOT NULL,status VARCHAR NOT NULL CHECK(status IN ('downloaded','source_only','unknown')),portrait_status VARCHAR NOT NULL,image_count INTEGER NOT NULL,downloaded_count INTEGER NOT NULL,source_portrait_count INTEGER NOT NULL,unknown_reason VARCHAR,source_id VARCHAR NOT NULL REFERENCES source(source_id),source_pointer VARCHAR NOT NULL);
"""


def retained_dom(raw):
    """Decode retained UTF-8 captures, including BOM, without replacement text."""
    try:
        decoded = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        decoded = raw
    return html.fromstring(decoded)


def retained_image_urls(node, page_url):
    """Resolve only explicit DOM image values and Brno's exact picfit recipe."""
    urls = {
        urljoin(page_url, node.get(field, ""))
        for field in ("src", "data-src", "data-lazy-src")
        if node.get(field)
    }
    urls.update(
        urljoin(page_url, part.strip().split()[0])
        for part in node.get("srcset", "").split(",")
        if part.strip()
    )
    if node.tag == "a" and node.get("href") and node.xpath(".//img"):
        urls.add(urljoin(page_url, node.get("href")))
    # The collector also retains literal CSS background images on named cards.
    urls.update(
        urljoin(page_url, match.group(2).strip())
        for match in re.finditer(
            r"background-image\s*:\s*url\(\s*(['\"]?)([^)\"']+)\1\s*\)",
            node.get("style", ""),
            re.IGNORECASE,
        )
    )
    for value in tuple(urls):
        parsed = urlparse(value)
        if (
            parsed.scheme == "https"
            and parsed.netloc == "www.brno.cz"
            and parsed.path == "/picfit/display"
            and not parsed.fragment
        ):
            query = parse_qs(parsed.query, keep_blank_values=True)
            originals = query.get("url", [])
            if len(originals) == 1:
                original = urlparse(originals[0])
                if (
                    original.scheme == "https"
                    and original.netloc == "www.brno.cz"
                    and original.path.startswith("/documents/")
                    and not original.query
                    and not original.fragment
                ):
                    urls.add(originals[0])
    return urls


def city_in_text(city, text):
    """Recognize explicit Czech case forms without a fuzzy place-name match."""
    forms = {
        "Brno": ("Brno", "Brna", "Brně", "Brnu", "Brnem"),
        "Praha": ("Praha", "Prahy", "Praze", "Prahu", "Prahou"),
        "Plzeň": ("Plzeň", "Plzně", "Plzni", "Plzní"),
        "Liberec": ("Liberec", "Liberce", "Liberci", "Libercem"),
        "Pardubice": ("Pardubice", "Pardubic", "Pardubicích", "Pardubicemi"),
        "Ostrava": ("Ostrava", "Ostravy", "Ostravě", "Ostravu", "Ostravou"),
        "Olomouc": ("Olomouc", "Olomouce", "Olomouci", "Olomoucí"),
        "České Budějovice": ("České Budějovice", "Českých Budějovic", "Českým Budějovicím", "Českých Budějovicích", "Českými Budějovicemi"),
        "Ústí nad Labem": ("Ústí nad Labem", "Ústím nad Labem"),
        "Hradec Králové": ("Hradec Králové", "Hradce Králové", "Hradci Králové", "Hradcem Králové"),
    }
    return any(
        re.search(r"(?<!\w)" + re.escape(folded(form)) + r"(?!\w)", folded(text)) is not None
        for form in forms.get(city, (city,))
    )


def pointer_value(document, pointer):
    if not isinstance(pointer, str) or not pointer.startswith("/"):
        raise ValueError("Exact source JSON pointer required")
    parts = pointer[1:].split("/")
    if len(parts) > 32:
        raise ValueError("Source image pointer is too deep")
    value = document
    try:
        for part in parts:
            part = part.replace("~1", "/").replace("~0", "~")
            value = value[int(part)] if isinstance(value, list) else value[part]
    except (IndexError, KeyError, TypeError, ValueError) as exc:
        raise ValueError("Source image pointer is missing") from exc
    return value


def folded(value):
    return " ".join(
        "".join(
            char
            for char in unicodedata.normalize("NFKD", value).casefold()
            if not unicodedata.combining(char)
        ).split()
    )


def image_info(raw):
    """Read raster type and declared dimensions without decoding or editing bytes."""
    if raw.startswith(b"\x89PNG\r\n\x1a\n") and len(raw) >= 24:
        return "image/png", *struct.unpack(">II", raw[16:24])
    if raw[:6] in (b"GIF87a", b"GIF89a") and len(raw) >= 10:
        return "image/gif", *struct.unpack("<HH", raw[6:10])
    if raw[:2] == b"\xff\xd8":
        index = 2
        while index + 4 <= len(raw):
            if raw[index] != 255:
                index += 1
                continue
            while index < len(raw) and raw[index] == 255:
                index += 1
            if index >= len(raw):
                break
            marker = raw[index]
            index += 1
            if marker in (0xD8, 0xD9) or 0xD0 <= marker <= 0xD7:
                continue
            if index + 2 > len(raw):
                break
            length = int.from_bytes(raw[index : index + 2], "big")
            if marker in (
                0xC0,
                0xC1,
                0xC2,
                0xC3,
                0xC5,
                0xC6,
                0xC7,
                0xC9,
                0xCA,
                0xCB,
                0xCD,
                0xCE,
                0xCF,
            ) and index + 7 <= len(raw):
                return (
                    "image/jpeg",
                    int.from_bytes(raw[index + 5 : index + 7], "big"),
                    int.from_bytes(raw[index + 3 : index + 5], "big"),
                )
            if length < 2:
                break
            index += length
    if raw[:4] == b"RIFF" and raw[8:12] == b"WEBP" and len(raw) >= 30:
        if raw[12:16] == b"VP8X":
            return (
                "image/webp",
                int.from_bytes(raw[24:27], "little") + 1,
                int.from_bytes(raw[27:30], "little") + 1,
            )
        if raw[12:16] == b"VP8 " and raw[23:26] == b"\x9d\x01\x2a":
            return (
                "image/webp",
                int.from_bytes(raw[26:28], "little") & 0x3FFF,
                int.from_bytes(raw[28:30], "little") & 0x3FFF,
            )
        if raw[12:16] == b"VP8L" and raw[20] == 0x2F:
            bits = int.from_bytes(raw[21:25], "little")
            return "image/webp", (bits & 0x3FFF) + 1, ((bits >> 14) & 0x3FFF) + 1
    if len(raw) >= 32 and raw[4:8] == b"ftyp":
        box_size = int.from_bytes(raw[:4], "big")
        if 16 <= box_size <= min(len(raw), 4096) and box_size % 4 == 0:
            brands = {
                raw[8:12],
                *(raw[index : index + 4] for index in range(16, box_size, 4)),
            }
            offset = raw.find(b"ispe", box_size, min(len(raw), 1_000_000))
            if brands & {b"avif", b"avis"} and offset >= 4 and offset + 16 <= len(raw):
                dimensions_size = int.from_bytes(raw[offset - 4 : offset], "big")
                if 20 <= dimensions_size <= len(raw) - offset + 4:
                    return (
                        "image/avif",
                        int.from_bytes(raw[offset + 8 : offset + 12], "big"),
                        int.from_bytes(raw[offset + 12 : offset + 16], "big"),
                    )
    raise ValueError("Unsupported or invalid retained raster")


def import_image_index(rows, inputs, path, pin_file):
    selected = Path(path)
    selected = selected if selected.is_absolute() else inputs.root / selected
    selected = selected.resolve()
    document, index_source = inputs.read(selected)
    if (
        not isinstance(document, dict)
        or document.get("schema") != "production-source-images-v1"
        or document.get("schema_version") != 1
    ):
        raise ValueError("Explicit source image index required")
    targets, images = document.get("targets"), document.get("images")
    if (
        not isinstance(targets, list)
        or not isinstance(images, list)
        or type(document.get("target_count")) is not int
        or document["target_count"] != len(targets)
    ):
        raise ValueError("Exact target coverage/count required")
    entities = {row["entity_id"]: row for row in rows["entity"]}
    areas = {row["area_id"]: row for row in rows["area"]}
    owners = {
        (row["account_id"], row["entity_id"])
        for row in rows["account_relation"]
        if row["status"] == "confirmed"
    }
    target_map, image_map = {}, {}

    def pin(reference):
        if not isinstance(reference, dict) or not isinstance(
            reference.get("path"), str
        ):
            raise TypeError("Pinned original image source path/hash required")
        local = Path(reference["path"])
        local = (local if local.is_absolute() else selected.parent / local).resolve()
        return local, pin_file(inputs, local, reference.get("sha256"))

    def strict_binding(source, source_ref, item, target):
        evidence = source.get("identity_evidence", {})
        reference = evidence.get("binding_review")
        review_path, review_source = pin(reference)
        reviews, loaded = inputs.read(review_path)
        verdict = pointer_value(reviews, reference.get("pointer"))
        reviewer = (
            verdict.get("reviewer", reviews.get("reviewer"))
            if isinstance(verdict, dict)
            else None
        )
        if not isinstance(reviewer, str) or not reviewer.removeprefix(
            "native:"
        ).startswith("/root/"):
            raise ValueError("Identified independent native portrait reviewer required")
        task = reviewer.removeprefix("native:").removeprefix("/root/")
        if not task or any(
            part in {"", ".", ".."} or re.fullmatch(r"[a-z0-9_]+", part) is None
            for part in task.split("/")
        ):
            raise ValueError(
                "Canonical nonempty native portrait reviewer task required"
            )
        review_root = inputs.root / "tmp/production/native" / task
        if not review_path.is_relative_to(review_root.resolve()):
            raise ValueError(
                "Portrait reviewer output must remain in its exact native task directory"
            )
        index_path = verdict.get(
            "source_index_path",
            verdict.get("index_snapshot_path", reviews.get("index_path")),
        )
        index_hash = verdict.get(
            "source_index_sha256",
            verdict.get("index_sha256", reviews.get("index_sha256")),
        )
        proposal_path, _ = pin({"path": index_path, "sha256": index_hash})
        native_root = (inputs.root / "tmp/production/native").resolve()
        collector = (
            proposal_path.relative_to(native_root).parts[0]
            if proposal_path.is_relative_to(native_root)
            else verdict.get("collector_task_path")
        )
        if not collector or task == str(collector).removeprefix("native:/root/"):
            raise ValueError("Portrait reviewer must differ from its image proposer")
        scope = evidence.get("binding_scope")
        if (
            loaded != review_source
            or not isinstance(verdict, dict)
            or verdict.get("decision") != "accept"
            or verdict.get("target_id") != target["target_id"]
            or verdict.get("original_image_url") != item["original_image_url"]
            or verdict.get("source_page_sha256") != source_ref.get("raw_page_sha256")
            or verdict.get("binding_scope") != scope
            or scope
            not in {
                "bounded_person_card",
                "dedicated_person_page",
                "target_specific_anchor",
            }
        ):
            raise ValueError("Exact source/target/image scoped binding review required")
        role_pattern = r"kandidat|candidate|zastupitel|council|primator|starost|poslanec|senator|radni|polit[iy]k|predseda"

        def official_publisher_city():
            reference = evidence.get("publisher_city_proof")
            if reference is None:
                return False
            proof_path, proof_id = pin(reference)
            proof, loaded = inputs.read(proof_path)
            reviewer = proof.get("reviewer", "").removeprefix("native:")
            task = reviewer.removeprefix("/root/")
            if (
                loaded != proof_id
                or proof.get("schema_version") != "independently-reviewed-municipal-publisher-v1"
                or proof.get("decision") != "accept"
                or proof.get("city") != target["city"]
                or not reviewer.startswith("/root/")
                or not task
                or any(re.fullmatch(r"[a-z0-9_]+", part) is None for part in task.split("/"))
                or not proof_path.is_relative_to((inputs.root / "tmp/production/native" / task).resolve())
                or task == str(collector).removeprefix("native:/root/")
            ):
                raise ValueError("Independent exact municipal publisher review required")
            page = urlparse(source_ref["url"])
            authority = urlparse(proof.get("source_url", ""))
            if (
                page.scheme != "https"
                or authority.scheme != "https"
                or page.hostname != proof.get("hostname")
                or authority.hostname != proof.get("hostname")
                or authority.username or authority.password
                or authority.port not in (None, 443)
            ):
                raise ValueError("Municipal publisher authority must bind exact source host")
            receipt_path, receipt_id = pin({"path": proof.get("retrieval_receipt_path"), "sha256": proof.get("retrieval_receipt_sha256")})
            receipt, loaded = inputs.read(receipt_path)
            if (
                loaded != receipt_id
                or receipt.get("final_url") != proof.get("source_url")
                or receipt.get("path") != proof.get("source_path")
                or receipt.get("sha256") != proof.get("source_sha256")
            ):
                raise ValueError("Municipal authority retrieval binding differs")
            raw_path, _ = pin({"path": proof.get("source_path"), "sha256": proof.get("source_sha256")})
            dom = retained_dom(raw_path.read_bytes())
            nodes = dom.xpath(proof.get("identity_pointer", ""))
            if len(nodes) != 1:
                raise ValueError("Exact municipal legal identity node required")
            actual = " ".join(nodes[0].text_content().split())
            if (
                actual != proof.get("identity_text")
                or re.search(r"(?<!\w)(?:statutarni mesto|mesto|obec)(?!\w)", folded(actual)) is None
                or re.search(r"(?<!\w)" + re.escape(folded(target["city"])) + r"(?!\w)", folded(actual)) is None
            ):
                raise ValueError("Municipal publisher city must exist in retained legal identity")
            return True

        def named(text):
            return (
                isinstance(text, str)
                and re.search(
                    r"(?<!\w)" + re.escape(folded(target["name"])) + r"(?!\w)",
                    folded(text),
                )
                is not None
            )

        def image_node(dom, binding):
            nodes = dom.xpath(binding.get("dom_pointer", ""))
            if len(nodes) != 1:
                raise ValueError("Scoped image source XPath must select one image")
            node = nodes[0]
            urls = retained_image_urls(node, source_ref["url"])
            if item["original_image_url"] not in urls:
                raise ValueError("Scoped image URL differs from retained DOM")
            return node

        for exact in verdict.get("exact_proof", []):
            packet_path, packet_id = pin(
                {
                    "path": exact.get("source_path"),
                    "sha256": exact.get("source_packet_sha256"),
                }
            )
            if packet_path.read_bytes().lstrip(b"\xef\xbb\xbf \t\r\n").startswith(b"<"):
                if exact.get("source_packet_sha256") != source_ref.get(
                    "raw_page_sha256"
                ):
                    continue
                raw_path = packet_path
            else:
                packet, loaded = inputs.read(packet_path)
                raw_hash = packet.get("raw_page_sha256", packet.get("raw_sha256"))
                if loaded != packet_id or raw_hash != source_ref.get("raw_page_sha256"):
                    continue
                original = packet.get("original_source", source.get("original_source"))
                raw_path = packet.get(
                    "raw_source_path",
                    packet.get("cache_raw_path", packet.get("raw_cache_path")),
                )
                if raw_path is None and isinstance(original, dict):
                    raw_path = original.get("path")
                if raw_path is None:
                    roster_source = verdict.get("roster_scope", {}).get(
                        "original_source", {}
                    )
                    if roster_source.get("sha256") == raw_hash:
                        raw_path = roster_source.get("path")
                if raw_path is None:
                    continue
                raw_path, _ = pin({"path": raw_path, "sha256": raw_hash})
            dom = retained_dom(raw_path.read_bytes())
            scope_nodes = dom.xpath(exact.get("dom_pointer", ""))
            if len(scope_nodes) != 1:
                continue
            node = scope_nodes[0]
            image = image_node(dom, {"dom_pointer": source.get("raw_dom_pointer")})
            context = " ".join(node.text_content().split())
            label = " ".join((image.get("alt", ""), image.get("title", ""), context, " ".join(node.itertext())))
            if (
                node.tag not in {"html", "body", "main", "footer"}
                and image in node.iter()
                and not any(n.tag == "footer" for n in node.iterancestors())
                and len(context) <= 8000
                and named(label)
                and re.search(role_pattern, folded(context))
                and city_in_text(target["city"], context)
            ):
                return
        proof = verdict.get("target_specific_proof")
        if isinstance(proof, dict) and isinstance(proof.get("sources"), list):
            binding = proof.get("image_page_binding")
            if not isinstance(binding, dict):
                raise TypeError(
                    "Target-specific image source binding must be an object"
                )
            binding_path, _ = pin(binding)
            if binding.get("sha256") != source_ref.get(
                "raw_page_sha256"
            ) or binding_path.suffix.lower() not in {".html", ".htm"}:
                raise ValueError(
                    "Target-specific image needs exact retained DOM source"
                )
            image_dom = retained_dom(binding_path.read_bytes())
            image = image_node(image_dom, binding)
            for anchor in proof["sources"]:
                anchor_path, anchor_id = pin(anchor)
                if anchor_path.suffix.lower() in {".html", ".htm"}:
                    if anchor.get("sha256") != binding.get("sha256"):
                        continue
                    dom = image_dom
                    name_nodes, role_nodes, city_nodes = [
                        dom.xpath(anchor.get(field, ""))
                        for field in (
                            "name_pointer",
                            "role_pointer",
                            "locality_pointer",
                        )
                    ]
                    if any(
                        len(nodes) != 1
                        for nodes in (name_nodes, role_nodes, city_nodes)
                    ):
                        continue
                    card, role_node, city_node = (
                        name_nodes[0],
                        role_nodes[0],
                        city_nodes[0],
                    )
                    name_text, role_text, city_text = [
                        " ".join(node.text_content().split())
                        for node in (card, role_node, city_node)
                    ]
                    # Adjacent block elements can concatenate under text_content().
                    name_text = " ".join(" ".join(card.itertext()).split())
                    if (
                        image not in card.iter()
                        or card.tag in {"html", "body", "main", "footer"}
                        or (role_node.tag != "h1" and role_node is not card and role_node not in card.iter())
                        or city_node.tag != "title"
                        or any(n.tag == "footer" for n in role_node.iterancestors())
                    ):
                        continue
                else:
                    anchor_doc, loaded = inputs.read(anchor_path)
                    if loaded != anchor_id:
                        continue
                    identity_pointer = "/candidates/" + target["entity_id"]
                    if not any(
                        relation["entity_id"] == target["entity_id"]
                        and relation["status"] == "confirmed"
                        and relation["source_id"] == anchor_id
                        and relation["source_pointer"] == identity_pointer
                        for relation in rows["account_relation"]
                    ) or (
                        anchor.get("name_pointer") != identity_pointer + "/name"
                        or not str(anchor.get("role_pointer", "")).startswith(
                            identity_pointer + "/public_role_evidence/"
                        )
                        or not str(anchor.get("locality_pointer", "")).startswith(
                            identity_pointer + "/locality_evidence/"
                        )
                    ):
                        continue
                    name_text = pointer_value(anchor_doc, anchor.get("name_pointer"))
                    role_text = pointer_value(anchor_doc, anchor.get("role_pointer"))
                    city_text = pointer_value(
                        anchor_doc, anchor.get("locality_pointer")
                    )
                    original = anchor.get("original_source_path")
                    if not isinstance(original, str):
                        continue
                    pin(
                        {
                            "path": original,
                            "sha256": anchor.get("original_source_sha256"),
                        }
                    )
                    context_nodes = image_dom.xpath(
                        binding.get(
                            "named_context_pointer", binding.get("dom_pointer", "")
                        )
                    )
                    if len(context_nodes) != 1:
                        continue
                    card = context_nodes[0]
                    label = " ".join(
                        (
                            card.get("alt", ""),
                            card.get("title", ""),
                            card.text_content(),
                        )
                    )
                    if (
                        (card is not image and image not in card.iter())
                        or card.tag in {"html", "body", "main", "footer"}
                        or len(label) > 3000
                        or not named(label)
                    ):
                        continue
                if (
                    named(name_text)
                    and anchor.get("exact_name") == target["name"]
                    and isinstance(role_text, str)
                    and isinstance(city_text, str)
                    and isinstance(anchor.get("exact_role"), str)
                    and folded(anchor["exact_role"]) in folded(role_text)
                    and re.search(role_pattern, folded(anchor["exact_role"]))
                    and city_in_text(target["city"], city_text)
                    and isinstance(anchor.get("exact_locality"), str)
                    and folded(anchor["exact_locality"]) in folded(city_text)
                ):
                    return
            raise ValueError(
                "Target-specific source role/city must bind an actual named image card/profile"
            )
        roster = verdict.get("roster_scope")
        if isinstance(roster, dict) and isinstance(roster.get("scope_source"), dict):
            scope_path, scope_source = pin(roster["scope_source"])
            packet, loaded = inputs.read(scope_path)
            node = pointer_value(packet, roster["scope_source"].get("pointer"))
            if (
                loaded != scope_source
                or packet.get("raw_sha256") != source_ref.get("raw_page_sha256")
                or not isinstance(node, dict)
            ):
                raise ValueError("Scoped source capture must bind exact original page")
            original_scope = packet.get("original_source")
            if not isinstance(original_scope, dict) or original_scope.get(
                "sha256"
            ) != packet.get("raw_sha256"):
                raise ValueError(
                    "Scoped original DOM hash must match captured page hash"
                )
            raw_scope_path, _ = pin(original_scope)
            if raw_scope_path.suffix.lower() not in {".html", ".htm"}:
                raise ValueError(
                    "Scoped roster needs retained original DOM to resolve ancestry"
                )
            scope_dom = retained_dom(raw_scope_path.read_bytes())
            root_pointer = node.get("dom_pointer")
            heading, city = node.get("heading", {}), node.get("city_title", {})
            publisher_city = official_publisher_city()
            if (
                not isinstance(root_pointer, str)
                or "footer" in root_pointer.lower()
                or not str(heading.get("dom_pointer", "")).startswith(
                    root_pointer + "/"
                )
                or re.search(r"/h[1-3](?:\[[1-9][0-9]*\])?$", str(heading.get("dom_pointer", ""))) is None
                or city.get("dom_pointer") != "/html/head/title"
                or not isinstance(heading.get("text"), str)
                or not re.search(role_pattern, folded(heading["text"]))
                or not isinstance(city.get("text"), str)
                or (not city_in_text(target["city"], city["text"] + " " + heading["text"]) and not publisher_city)
            ):
                raise ValueError(
                    "Primary scoped political roster heading and city title required"
                )
            for card in node.get("cards", []):
                card_pointer = card.get("dom_pointer")
                if (
                    not isinstance(card_pointer, str)
                    or not card_pointer.startswith(root_pointer + "/")
                    or not named(card.get("text"))
                ):
                    continue
                card_nodes = scope_dom.xpath(card_pointer)
                root_nodes = scope_dom.xpath(root_pointer)
                heading_nodes = scope_dom.xpath(heading["dom_pointer"])
                title_nodes = scope_dom.xpath(city["dom_pointer"])
                if (
                    any(
                        len(nodes) != 1
                        for nodes in (
                            card_nodes,
                            root_nodes,
                            heading_nodes,
                            title_nodes,
                        )
                    )
                    or card_nodes[0] not in root_nodes[0].iter()
                    or heading_nodes[0] not in root_nodes[0].iter()
                    or any(ancestor.tag == "footer" for ancestor in heading_nodes[0].iterancestors())
                    or not named(card_nodes[0].text_content())
                    or " ".join(heading_nodes[0].text_content().split())
                    != " ".join(heading["text"].split())
                    or " ".join(title_nodes[0].text_content().split())
                    != " ".join(city["text"].split())
                    or not re.search(
                        role_pattern, folded(heading_nodes[0].text_content())
                    )
                    or (not city_in_text(target["city"], title_nodes[0].text_content() + " " + heading_nodes[0].text_content()) and not publisher_city)
                ):
                    continue
                actual_image = image_node(
                    scope_dom, {"dom_pointer": source.get("raw_dom_pointer")}
                )
                if actual_image not in card_nodes[0].iter():
                    continue
                if any(
                    image.get("url") == item["original_image_url"]
                    and isinstance(image.get("dom_pointer"), str)
                    and image["dom_pointer"].startswith(card_pointer + "/")
                    for image in card.get("images", [])
                ):
                    return
        raise ValueError(
            "Portrait source scope must physically bind heading/card/image; copied global metadata rejected"
        )

    for index, target in enumerate(targets):
        if not isinstance(target, dict):
            raise TypeError("Image target must be an object")
        target_id = target.get("target_id")
        entity_id = target.get("entity_id", target_id)
        entity = entities.get(entity_id)
        if (
            not isinstance(target_id, str)
            or target_id in target_map
            or not entity
            or entity["kind"] != "current_candidacy"
            or entity["name"] != target.get("name")
            or areas[entity["area_id"]]["name"] != target.get("city")
        ):
            raise ValueError("Unique exact current person/city image target required")
        if entity_id in {row["entity_id"] for row in target_map.values()}:
            raise ValueError("Duplicate photo coverage entity")
        target_map[target_id] = {
            **target,
            "entity_id": entity_id,
            "source_pointer": f"/targets/{index}",
        }

    for index, item in enumerate(images):
        if not isinstance(item, dict):
            raise TypeError("Source image must be an object")
        identifier, target = item.get("image_id"), target_map.get(item.get("target_id"))
        if (
            not isinstance(identifier, str)
            or identifier in image_map
            or not target
            or item.get("entity_id", item.get("target_id")) != target["entity_id"]
        ):
            raise ValueError("Unique source image with exact covered target required")
        kind, relation = item.get("kind"), item.get("relation_status")
        if (
            kind not in {"source_bound_portrait", "owned_account_avatar"}
            or relation not in {"source_identified", "unknown"}
            or item.get("depicted_person_status", "unknown") != "unknown"
        ):
            raise ValueError("Image source attribution cannot infer depicted identity")
        source_ref = item.get("source_page")
        if not isinstance(source_ref, dict):
            raise TypeError("Source image page reference must be an object")
        source_path, source_id = pin(source_ref)
        source, loaded = inputs.read(source_path)
        if source_id != loaded or not isinstance(source, dict):
            raise ValueError("Source image extraction changed or is malformed")
        image_url, page_url = (
            public_url(item.get("original_image_url")),
            public_url(source_ref.get("url")),
        )
        observed_at = timestamp(item.get("observed_at"))
        if (
            not image_url
            or not page_url
            or not observed_at
            or pointer_value(source, item.get("source_image_pointer")) != image_url
        ):
            raise ValueError("Image URL/time differs from exact source pointer")
        text = pointer_value(source, source_ref.get("text_pointer"))
        evidence = item.get("identity_evidence")
        if not isinstance(text, str) or not isinstance(evidence, dict):
            raise TypeError("Retained image source context required")
        account_id = item.get("account_id") if kind == "owned_account_avatar" else None
        if kind == "owned_account_avatar":
            if isinstance(account_id, str) and account_id.startswith("facebook:"):
                require_facebook_avatar(
                    rows, inputs, source, item, target, page_url, pin, pointer_value
                )
            else:
                prefix = item["source_image_pointer"].rsplit("/", 1)[0]
                profile = pointer_value(source, prefix)
                if (
                    (account_id, target["entity_id"]) not in owners
                    or source.get("schema_version") != 1
                    or source.get("policy_version") != "public-metadata-v1"
                    or source.get("actor") != "apify/instagram-profile-scraper"
                    or re.fullmatch(r"/items/[0-9]+", prefix) is None
                    or not isinstance(profile, dict)
                    or profile.get("private") is not False
                    or account_id != "instagram:" + str(profile.get("username", "")).lower()
                    or not item["source_image_pointer"].endswith(
                        ("/profilePicUrl", "/profilePicUrlHD")
                    )
                    or urlparse(page_url).hostname
                    not in {"instagram.com", "www.instagram.com"}
                    or urlparse(page_url).path.strip("/").lower()
                    != str(profile.get("username", "")).lower()
                ):
                    raise ValueError(
                        "Avatar requires exact independently owned public account source"
                    )
        else:
            if (
                source.get("target_id") != target["target_id"]
                or source.get("source_page_url") != page_url
            ):
                raise ValueError("Portrait source must label exact named target")
            if relation == "source_identified" and (
                re.search(
                    r"(?<!\w)" + re.escape(folded(target["name"])) + r"(?!\w)",
                    folded(text),
                )
                is None
                or evidence.get("exact_name") != target["name"]
            ):
                raise ValueError(
                    "Source-identified portrait requires retained role/locality context"
                )
            if relation == "source_identified":
                strict_binding(source, source_ref, item, target)
            original = source.get("original_source")
            if original is not None:
                original_path, _ = pin(original)
                if original_path.suffix.lower() in {".html", ".htm"}:
                    dom = retained_dom(original_path.read_bytes())
                    nodes = dom.xpath(source.get("raw_dom_pointer", ""))
                    if len(nodes) != 1:
                        raise ValueError("Original portrait DOM pointer differs")
                    node = nodes[0]
                    urls = retained_image_urls(node, page_url)
                    if image_url not in urls:
                        raise ValueError(
                            "Portrait URL differs from pinned original DOM"
                        )
        download = item.get("download")
        status = item.get(
            "download_status",
            "downloaded" if isinstance(download, dict) else "source_only",
        )
        if status not in {"downloaded", "failed", "source_only"}:
            raise ValueError("Explicit image download status required")
        local_path = blob_source = size = mime = width = height = blob_sha = None
        if status == "downloaded":
            if not isinstance(download, dict):
                raise ValueError("Downloaded image needs retained bytes")
            local, blob_source = pin(
                {"path": download.get("local_path"), "sha256": download.get("sha256")}
            )
            raw = local.read_bytes()
            size, (mime, width, height) = len(raw), image_info(raw)
            if (
                size <= 0
                or size > 8_000_000
                or type(download.get("bytes")) is not int
                or size != download["bytes"]
                or mime != download.get("content_type")
                or width != download.get("width")
                or height != download.get("height")
                or not 0 < width <= 20000
                or not 0 < height <= 20000
            ):
                raise ValueError("Retained image bytes/type/dimensions differ")
            local_path, blob_sha = str(local), download["sha256"]
        elif download is not None:
            raise ValueError("Failed/source-only image cannot claim retained bytes")
        image_map[identifier] = {
            "image_id": identifier,
            "entity_id": target["entity_id"],
            "target_id": target["target_id"],
            "kind": kind,
            "relation_status": relation,
            "depicted_person_status": "unknown",
            "download_status": status,
            "local_path": local_path,
            "sha256": blob_sha,
            "bytes": size,
            "content_type": mime,
            "width": width,
            "height": height,
            "original_image_url": image_url,
            "observed_at": observed_at,
            "source_page_url": page_url,
            "source_page_sha256": source_ref["sha256"],
            "source_image_pointer": item["source_image_pointer"],
            "source_text_pointer": source_ref["text_pointer"],
            "identity_evidence": serialized(evidence),
            "account_id": account_id,
            "failure_reason": item.get("failure_reason"),
            "source_id": index_source,
            "source_page_id": source_id,
            "blob_source_id": blob_source,
            "source_pointer": f"/images/{index}",
        }
    rows["source_image"] = list(image_map.values())
    coverage = []
    for target in target_map.values():
        target_images = [
            row for row in image_map.values() if row["target_id"] == target["target_id"]
        ]
        identified = [
            row
            for row in target_images
            if row["relation_status"] == "source_identified"
        ]
        downloaded = [
            row for row in identified if row["download_status"] == "downloaded"
        ]
        status = (
            "downloaded" if downloaded else "source_only" if identified else "unknown"
        )
        declared_ids = target.get("image_ids", [])
        if (
            not isinstance(declared_ids, list)
            or len(set(declared_ids)) != len(declared_ids)
            or any(
                identifier not in image_map
                or image_map[identifier]["target_id"] != target["target_id"]
                for identifier in declared_ids
            )
        ):
            raise ValueError("Target image IDs must bind exact images")
        if target.get("status", status) != status or (
            status == "unknown" and not isinstance(target.get("unknown_reason"), str)
        ):
            raise ValueError("Photo coverage status/gap differs from retained images")
        coverage.append(
            {
                "entity_id": target["entity_id"],
                "target_id": target["target_id"],
                "name": target["name"],
                "city": target["city"],
                "status": status,
                "portrait_status": str(target.get("portrait_status", "unknown")),
                "image_count": len(target_images),
                "downloaded_count": len(downloaded),
                "source_portrait_count": sum(
                    row["kind"] == "source_bound_portrait" for row in downloaded
                ),
                "unknown_reason": target.get("unknown_reason"),
                "source_id": index_source,
                "source_pointer": target["source_pointer"],
            }
        )
    rows["entity_photo_coverage"] = coverage
